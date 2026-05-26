import pytest
from fastapi import HTTPException

from src.api.run_events import (
    MAX_LIMIT,
    MAX_PAGINATION_WINDOW,
    RunEventService,
)


def _service(allowed=True):
    calls = []

    def lookup(run_id, limit, offset):
        calls.append((run_id, limit, offset))
        return [{"id": f"event-{offset}", "run_id": run_id}]

    def can_access(workspace_id, run_id):
        return allowed and workspace_id == "workspace-a" and run_id == "run-1"

    return RunEventService(lookup, can_access), calls


def test_authorized_run_event_request_uses_bounded_window():
    service, calls = _service()

    response = service.list_events(
        workspace_id="workspace-a",
        run_id="run-1",
        limit=50,
        offset=10,
    )

    assert response["limit"] == 50
    assert response["offset"] == 10
    assert response["events"] == [{"id": "event-10", "run_id": "run-1"}]
    assert calls == [("run-1", 50, 10)]


@pytest.mark.parametrize(
    ("limit", "offset", "status_code"),
    [
        (0, 0, 400),
        (MAX_LIMIT + 1, 0, 400),
        (10, -1, 400),
        (100, MAX_PAGINATION_WINDOW, 416),
    ],
)
def test_malformed_pagination_rejects_before_lookup(
    limit,
    offset,
    status_code,
):
    service, calls = _service()

    with pytest.raises(HTTPException) as excinfo:
        service.list_events(
            workspace_id="workspace-a",
            run_id="run-1",
            limit=limit,
            offset=offset,
        )

    assert excinfo.value.status_code == status_code
    assert calls == []


def test_unauthorized_run_rejects_before_lookup():
    service, calls = _service(allowed=False)

    with pytest.raises(HTTPException) as excinfo:
        service.list_events(
            workspace_id="workspace-a",
            run_id="run-1",
            limit=10,
            offset=0,
        )

    assert excinfo.value.status_code == 403
    assert calls == []


def test_blank_identifiers_reject_before_lookup():
    service, calls = _service()

    with pytest.raises(HTTPException) as excinfo:
        service.list_events(
            workspace_id=" ",
            run_id="run-1",
            limit=10,
            offset=0,
        )

    assert excinfo.value.status_code == 400
    assert calls == []
