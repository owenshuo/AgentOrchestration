import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import (
    ForwardedHeaderMiddleware,
    request_proxy_context,
)


def _request(headers=None):
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or [])
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/agents",
            "headers": raw_headers,
            "client": ("198.51.100.10", 4444),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


async def _ok_handler(request):
    assert request_proxy_context.get()["forwarded_for"] == "203.0.113.10"
    return Response("ok")


async def _raising_handler(request):
    assert request_proxy_context.get()["forwarded_for"] == "203.0.113.10"
    raise RuntimeError("handler failed")


def test_forwarded_headers_are_accepted_and_context_is_cleared():
    middleware = ForwardedHeaderMiddleware(app=None)

    response = asyncio.run(
        middleware.dispatch(
            _request([("x-forwarded-for", "203.0.113.10")]),
            _ok_handler,
        )
    )

    assert response.status_code == 200
    assert response.headers["x-forwarded-header-status"] == "accepted"
    assert request_proxy_context.get() is None


def test_conflicting_forwarded_header_families_fail_closed():
    middleware = ForwardedHeaderMiddleware(app=None)

    response = asyncio.run(
        middleware.dispatch(
            _request(
                [
                    ("forwarded", "for=203.0.113.10;proto=https"),
                    ("x-forwarded-for", "203.0.113.10"),
                ]
            ),
            _ok_handler,
        )
    )

    assert response.status_code == 400
    assert response.headers["x-forwarded-header-status"] == "rejected"
    assert (
        response.headers["x-forwarded-header-reason"]
        == "mixed_forwarded_header_families"
    )
    assert request_proxy_context.get() is None


def test_x_forwarded_for_and_real_ip_mismatch_fail_closed():
    middleware = ForwardedHeaderMiddleware(app=None)

    response = asyncio.run(
        middleware.dispatch(
            _request(
                [
                    ("x-forwarded-for", "203.0.113.10, 198.51.100.1"),
                    ("x-real-ip", "198.51.100.2"),
                ]
            ),
            _ok_handler,
        )
    )

    assert response.status_code == 400
    assert (
        response.headers["x-forwarded-header-reason"]
        == "client_ip_mismatch"
    )


def test_duplicate_proto_values_fail_closed_before_handler_runs():
    called = False
    middleware = ForwardedHeaderMiddleware(app=None)

    async def handler(request):
        nonlocal called
        called = True
        return Response("ok")

    response = asyncio.run(
        middleware.dispatch(
            _request(
                [
                    ("x-forwarded-proto", "https"),
                    ("x-forwarded-proto", "http"),
                ]
            ),
            handler,
        )
    )

    assert response.status_code == 400
    assert response.headers["x-forwarded-header-reason"] == (
        "multiple_forwarded_proto"
    )
    assert called is False


def test_proxy_context_is_cleared_when_handler_raises():
    middleware = ForwardedHeaderMiddleware(app=None)

    with pytest.raises(RuntimeError):
        asyncio.run(
            middleware.dispatch(
                _request([("x-forwarded-for", "203.0.113.10")]),
                _raising_handler,
            )
        )

    assert request_proxy_context.get() is None
