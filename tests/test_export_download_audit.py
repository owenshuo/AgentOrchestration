from fastapi.testclient import TestClient

from src.api.export_audit import export_downloads
from src.api.server import create_app


def setup_function():
    export_downloads.reset()


def _client():
    return TestClient(create_app())


def test_api_export_download_records_successful_access():
    export_downloads.register_export(
        "export-1",
        b"export-data",
        owner="user-1",
        direct_token="token-1",
    )

    response = _client().get(
        "/api/v2/exports/export-1/download",
        headers={"Authorization": "Bearer token", "X-Actor-ID": "user-1"},
    )

    assert response.status_code == 200
    assert response.content == b"export-data"
    event = export_downloads.audit_events()[-1]
    assert event.actor == "user-1"
    assert event.export_id == "export-1"
    assert event.result == "success"
    assert event.path == "api"
    assert event.timestamp > 0


def test_api_export_download_records_failed_access_before_error():
    export_downloads.register_export(
        "export-2",
        b"secret-data",
        owner="owner",
    )

    response = _client().get(
        "/api/v2/exports/export-2/download",
        headers={"Authorization": "Bearer token", "X-Actor-ID": "intruder"},
    )

    assert response.status_code == 403
    event = export_downloads.audit_events()[-1]
    assert event.actor == "intruder"
    assert event.export_id == "export-2"
    assert event.result == "forbidden"
    assert event.path == "api"


def test_direct_export_download_records_success_and_unknown_links():
    export_downloads.register_export(
        "export-3",
        b"direct-data",
        owner="owner",
        direct_token="direct-token",
    )
    client = _client()

    success = client.get(
        "/api/v2/exports/direct/direct-token",
        headers={"Authorization": "Bearer token", "X-Actor-ID": "link-user"},
    )
    failure = client.get(
        "/api/v2/exports/direct/missing-token",
        headers={"Authorization": "Bearer token", "X-Actor-ID": "link-user"},
    )

    assert success.status_code == 200
    assert success.content == b"direct-data"
    assert failure.status_code == 404
    events = export_downloads.audit_events()
    assert events[-2].actor == "link-user"
    assert events[-2].export_id == "export-3"
    assert events[-2].result == "success"
    assert events[-2].path == "direct"
    assert events[-1].actor == "link-user"
    assert events[-1].export_id == "unknown"
    assert events[-1].result == "not_found"
    assert events[-1].path == "direct"
