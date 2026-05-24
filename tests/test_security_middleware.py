import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import SecurityMiddleware


def build_client(require_https_proxy=True):
    app = FastAPI()
    calls = []

    @app.get("/ok")
    async def ok(request: Request):
        calls.append(request.state.ao_security_decision)
        return {"ok": True}

    @app.get("/boom")
    async def boom(request: Request):
        calls.append(request.state.ao_security_decision)
        raise RuntimeError("handler failed")

    app.add_middleware(
        SecurityMiddleware,
        require_https_proxy=require_https_proxy,
    )
    return TestClient(app, raise_server_exceptions=False), calls


def test_production_proxy_allows_https_before_handler_runs():
    client, calls = build_client()

    response = client.get("/ok", headers={"X-Forwarded-Proto": "https"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["X-AO-Security-Decision"] == "allowed"
    assert calls == ["allowed"]


def test_production_proxy_rejects_insecure_scheme_before_stateful_work(caplog):
    client, calls = build_client()

    with caplog.at_level(logging.WARNING, logger="src.api.middleware"):
        response = client.get(
            "/ok?token=secret",
            headers={"X-Forwarded-Proto": "http"},
        )

    assert response.status_code == 400
    assert response.text == "HTTPS required"
    assert response.headers["X-AO-Security-Decision"] == "rejected"
    assert calls == []
    assert "secret" not in caplog.text
    assert "X-Forwarded-Proto" not in caplog.text


def test_forwarded_header_proto_is_honored():
    client, calls = build_client()

    response = client.get(
        "/ok",
        headers={"Forwarded": "for=192.0.2.60;proto=https;by=203.0.113.43"},
    )

    assert response.status_code == 200
    assert calls == ["allowed"]


def test_disabled_proxy_mode_does_not_require_https():
    client, calls = build_client(require_https_proxy=False)

    response = client.get("/ok", headers={"X-Forwarded-Proto": "http"})

    assert response.status_code == 200
    assert calls == ["allowed"]


def test_exception_path_clears_request_local_security_state(monkeypatch):
    cleared = []

    from src.api import middleware

    original_clear = middleware._clear_security_state

    def record_clear(request):
        cleared.append(dict(request.state._state))
        original_clear(request)

    monkeypatch.setattr(middleware, "_clear_security_state", record_clear)
    client, calls = build_client()

    response = client.get("/boom", headers={"X-Forwarded-Proto": "https"})

    assert response.status_code == 500
    assert calls == ["allowed"]
    assert cleared == [{"ao_security_decision": "allowed"}]


def test_forwarded_http_proto_is_rejected():
    client, calls = build_client()

    response = client.get(
        "/ok",
        headers={"Forwarded": "for=192.0.2.60;proto=http"},
    )

    assert response.status_code == 400
    assert calls == []
