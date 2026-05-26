import pytest
from fastapi.testclient import TestClient

from src.api.routes import live_update_auth
from src.api.server import create_app
from src.common.live_updates_auth import (
    LiveUpdateAuthError,
    LiveUpdateAuthService,
    LiveUpdateCredential,
)


def credential(**overrides):
    values = {
        "principal_id": "user-1",
        "workspace_id": "workspace-1",
        "roles": {"admin"},
        "scopes": {"live_updates:mint"},
        "expires_at": 9999999999.0,
        "not_before": 0.0,
        "revoked": False,
    }
    values.update(overrides)
    return LiveUpdateCredential(**values)


def test_service_rejects_anonymous_minting():
    service = LiveUpdateAuthService(clock=lambda: 1000.0)

    with pytest.raises(LiveUpdateAuthError, match="authentication required"):
        service.mint("workspace-1")

    assert service.audit_report()[-1]["details"]["reason"] == "anonymous"


def test_service_rejects_revoked_stale_and_insufficient_credentials():
    service = LiveUpdateAuthService(clock=lambda: 1000.0)
    cases = {
        "revoked": credential(revoked=True),
        "expired": credential(expires_at=999.0),
        "not_before": credential(not_before=1001.0),
        "missing_scope": credential(scopes=set()),
        "missing_role": credential(roles={"viewer"}),
    }

    for token, value in cases.items():
        service.register_bearer(token, value)
        with pytest.raises(LiveUpdateAuthError):
            service.mint("workspace-1", authorization_header=f"Bearer {token}")

    reasons = [event["details"]["reason"] for event in service.audit_report()]
    assert reasons == [
        "revoked",
        "expired",
        "not_before",
        "missing_scope",
        "missing_role",
    ]


def test_service_rejects_workspace_mismatch_before_minting():
    service = LiveUpdateAuthService(clock=lambda: 1000.0)
    service.register_bearer("good", credential(workspace_id="workspace-2"))

    with pytest.raises(LiveUpdateAuthError, match="workspace mismatch"):
        service.mint("workspace-1", authorization_header="Bearer good")

    assert service.audit_report()[-1]["details"]["reason"] == (
        "workspace_mismatch"
    )


def test_service_mints_for_authorized_bearer_and_browser_session():
    service = LiveUpdateAuthService(clock=lambda: 1000.0, token_ttl=60.0)
    service.register_bearer("bearer", credential(principal_id="api-user"))
    service.register_browser_session(
        "session",
        credential(principal_id="browser-user"),
    )

    bearer = service.mint("workspace-1", authorization_header="Bearer bearer")
    browser = service.mint("workspace-1", browser_session="session")

    assert bearer.principal_id == "api-user"
    assert browser.principal_id == "browser-user"
    assert bearer.expires_at == 1060.0
    assert browser.token != bearer.token


def test_route_requires_authenticated_authorized_principal():
    live_update_auth.reset()
    live_update_auth.register_bearer("route-token", credential())
    client = TestClient(create_app())

    anonymous = client.post(
        "/api/v2/live-updates/token",
        json={"workspace_id": "workspace-1"},
    )
    authorized = client.post(
        "/api/v2/live-updates/token",
        json={"workspace_id": "workspace-1"},
        headers={"Authorization": "Bearer route-token"},
    )

    assert anonymous.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["workspace_id"] == "workspace-1"
    assert "token" in authorized.json()


def test_route_accepts_authorized_browser_session_cookie():
    live_update_auth.reset()
    live_update_auth.register_browser_session(
        "browser-session",
        credential(principal_id="browser-user"),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/live-updates/token",
        json={"workspace_id": "workspace-1"},
        cookies={"ao_session": "browser-session"},
    )

    assert response.status_code == 200
    assert response.json()["principal_id"] == "browser-user"


def test_audit_does_not_include_raw_credentials_or_websocket_tokens():
    service = LiveUpdateAuthService(clock=lambda: 1000.0)
    service.register_bearer("super-secret-bearer", credential())

    minted = service.mint(
        "workspace-1",
        authorization_header="Bearer super-secret-bearer",
    )
    audit_text = str(service.audit_report())

    assert "super-secret-bearer" not in audit_text
    assert minted.token not in audit_text
