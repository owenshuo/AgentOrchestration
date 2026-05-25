from fastapi.testclient import TestClient

from src.api.server import create_app


def auth_headers(role="admin", token="fresh-token", workspace="workspace-a"):
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace,
        "X-Active-Role": role,
    }


def test_openapi_schema_requires_authentication():
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 401


def test_openapi_schema_rejects_stale_or_revoked_tokens():
    client = TestClient(create_app())

    stale = client.get(
        "/openapi.json",
        headers=auth_headers(token="stale"),
    )
    revoked = client.get(
        "/openapi.json",
        headers=auth_headers(token="revoked"),
    )

    assert stale.status_code == 401
    assert revoked.status_code == 401


def test_openapi_schema_requires_workspace_context():
    client = TestClient(create_app())

    response = client.get(
        "/openapi.json",
        headers=auth_headers(workspace=""),
    )

    assert response.status_code == 403


def test_openapi_schema_rejects_insufficient_role():
    client = TestClient(create_app())

    response = client.get(
        "/openapi.json",
        headers=auth_headers(role="viewer"),
    )

    assert response.status_code == 403


def test_authorized_workspace_admin_can_fetch_openapi_schema():
    client = TestClient(create_app())

    response = client.get("/openapi.json", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Agent Orchestrator API"


def test_browser_docs_entrypoint_requires_same_auth_policy():
    client = TestClient(create_app())

    anonymous = client.get("/api/docs")
    authorized = client.get("/api/docs", headers=auth_headers(role="owner"))

    assert anonymous.status_code == 401
    assert authorized.status_code == 200
