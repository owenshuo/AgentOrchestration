import base64
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import AuthenticationError, validate_worker_token
from src.api.middleware import AuthMiddleware


def token(claims):
    payload = json.dumps(claims).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def auth_header(claims):
    return {"Authorization": f"Bearer {token(claims)}"}


def create_test_client():
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/v2/workers/current")
    async def current_worker():
        return {"ok": True}

    return TestClient(app)


def valid_claims(**overrides):
    claims = {
        "sub": "worker-1",
        "workspace": "workspace-1",
        "role": "worker",
        "scopes": ["worker:request"],
        "nbf": time.time() - 60,
        "exp": time.time() + 60,
    }
    claims.update(overrides)
    return claims


def test_worker_token_rejects_not_before_in_future():
    with pytest.raises(AuthenticationError, match="not valid yet"):
        validate_worker_token(token(valid_claims(nbf=time.time() + 60)))


def test_worker_token_rejects_revoked_principal():
    with pytest.raises(AuthenticationError, match="revoked"):
        validate_worker_token(token(valid_claims(revoked=True)))


def test_worker_token_rejects_anonymous_principal():
    with pytest.raises(AuthenticationError, match="anonymous"):
        validate_worker_token(token(valid_claims(sub="", anonymous=True)))


def test_worker_token_rejects_insufficient_scope():
    with pytest.raises(AuthenticationError, match="insufficient scope"):
        validate_worker_token(
            token(valid_claims(role="viewer", scopes=["agent:read"]))
        )


def test_worker_token_accepts_authorized_principal():
    principal = validate_worker_token(token(valid_claims()))

    assert principal.subject == "worker-1"
    assert principal.workspace == "workspace-1"
    assert "worker:request" in principal.scopes


def test_worker_request_rejects_not_before_token_before_route_handler():
    client = create_test_client()

    response = client.get(
        "/api/v2/workers/current",
        headers=auth_header(valid_claims(nbf=time.time() + 60)),
    )

    assert response.status_code == 401


def test_worker_request_rejects_missing_or_malformed_token():
    client = create_test_client()

    missing = client.get("/api/v2/workers/current")
    malformed = client.get(
        "/api/v2/workers/current",
        headers={"Authorization": "Bearer not-json"},
    )

    assert missing.status_code == 401
    assert malformed.status_code == 401


def test_worker_request_allows_authorized_token_client():
    client = create_test_client()

    response = client.get(
        "/api/v2/workers/current",
        headers=auth_header(valid_claims()),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
