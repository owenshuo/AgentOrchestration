import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.api.middleware import (
    AuthMiddleware,
    LoggingMiddleware,
    get_request_context,
)


def make_request(headers=None, path="/api/v2/agents"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in (headers or {}).items()
            ],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "query_string": b"",
        }
    )


def test_correlation_id_is_scoped_to_workspace_and_role():
    async def run_test():
        middleware = LoggingMiddleware(app=None)
        seen = {}

        async def call_next(request):
            context = get_request_context()
            seen["first"] = context
            return Response("ok")

        request = make_request(
            {
                "X-Correlation-ID": "shared-correlation",
                "X-Workspace-ID": "workspace-a",
                "X-Active-Role": "admin",
            }
        )
        response = await middleware.dispatch(request, call_next)

        assert response.headers["X-Correlation-ID"] == (
            seen["first"].correlation_id
        )
        assert seen["first"].workspace_id == "workspace-a"
        assert seen["first"].active_role == "admin"
        assert seen["first"].correlation_id != "shared-correlation"
        assert get_request_context() is None

        async def second_call_next(request):
            seen["second"] = get_request_context()
            return Response("ok")

        second = make_request(
            {
                "X-Correlation-ID": "shared-correlation",
                "X-Workspace-ID": "workspace-b",
                "X-Active-Role": "admin",
            }
        )
        await middleware.dispatch(second, second_call_next)

        assert seen["second"].correlation_id != seen["first"].correlation_id
        assert get_request_context() is None

    asyncio.run(run_test())


def test_protected_requests_require_workspace_context():
    async def run_test():
        middleware = AuthMiddleware(app=None)

        async def call_next(request):
            raise AssertionError("protected request should be rejected early")

        request = make_request({"Authorization": "Bearer token"})
        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403
        assert get_request_context() is None

    asyncio.run(run_test())


def test_request_context_is_cleared_after_exception():
    async def run_test():
        middleware = LoggingMiddleware(app=None)

        async def call_next(request):
            assert get_request_context() is not None
            raise RuntimeError("boom")

        request = make_request(
            {
                "X-Correlation-ID": "shared-correlation",
                "X-Workspace-ID": "workspace-a",
                "X-Active-Role": "admin",
            }
        )

        with pytest.raises(RuntimeError):
            await middleware.dispatch(request, call_next)

        assert get_request_context() is None

    asyncio.run(run_test())
