from fastapi.testclient import TestClient

from src.api.server import create_app


def token_headers(
    token="fresh-token",
    session_generation="rotation-2",
    token_generation="rotation-2",
    role="admin",
    workspace="workspace-a",
):
    return {
        "Authorization": f"Bearer {token}",
        "X-Session-Generation": session_generation,
        "X-Token-Generation": token_generation,
        "X-Workspace-Role": role,
        "X-Workspace-ID": workspace,
    }


def browser_headers(
    session_generation="rotation-2",
    token_generation="rotation-2",
    role="admin",
    workspace="workspace-a",
):
    return {
        "X-Session-Generation": session_generation,
        "X-Token-Generation": token_generation,
        "X-Workspace-Role": role,
        "X-Workspace-ID": workspace,
    }


def test_dashboard_api_rejects_anonymous_principal():
    client = TestClient(create_app())

    response = client.get("/api/v2/agents")

    assert response.status_code == 401
    assert response.text == "anonymous principal denied"


def test_dashboard_api_rejects_revoked_or_stale_tokens():
    client = TestClient(create_app())

    revoked = client.get(
        "/api/v2/agents",
        headers=token_headers(token="revoked"),
    )
    stale = client.get("/api/v2/agents", headers=token_headers(token="stale"))

    assert revoked.status_code == 401
    assert stale.status_code == 401


def test_dashboard_api_rejects_refresh_token_rotation_mismatch():
    client = TestClient(create_app())

    response = client.get(
        "/api/v2/agents",
        headers=token_headers(
            session_generation="rotation-3",
            token_generation="rotation-2",
        ),
    )

    assert response.status_code == 401
    assert "not bound to current session rotation" in response.text


def test_dashboard_api_rejects_insufficient_workspace_role():
    client = TestClient(create_app())

    response = client.get(
        "/api/v2/agents",
        headers=token_headers(role="viewer"),
    )

    assert response.status_code == 403
    assert response.text == "insufficient workspace role"


def test_browser_session_cookie_uses_same_rotation_guard():
    client = TestClient(create_app())
    client.cookies.set("dashboard_session", "browser-session-token")

    response = client.get(
        "/api/v2/agents",
        headers=browser_headers(),
    )

    assert response.status_code == 200
    assert response.json()["agents"] == []


def test_authorized_token_client_can_complete_dashboard_workflow():
    client = TestClient(create_app())

    response = client.get("/api/v2/agents", headers=token_headers())

    assert response.status_code == 200
    assert response.json()["agents"] == []
