"""Regression tests for bulk export filter validation."""

from datetime import date

import pytest

from src.data.exports import (
    ExportFilterValidationError,
    ExportJobService,
    normalize_export_filters,
)


class RecordingQueue:
    def __init__(self):
        self.tasks = []

    def enqueue(self, task, queue="default", priority=0):
        self.tasks.append({"task": task, "queue": queue, "priority": priority})
        return f"queued-{len(self.tasks)}"


def test_normalizes_dates_workspace_and_status():
    filters = normalize_export_filters(
        {
            "date_from": " 2026-01-01 ",
            "date_to": date(2026, 1, 31),
            "workspace_id": " workspace-1 ",
            "status": " Completed ",
        }
    )

    assert filters.to_dict() == {
        "date_from": "2026-01-01",
        "date_to": "2026-01-31",
        "workspace_id": "workspace-1",
        "status": "completed",
    }


def test_boundary_same_day_range_is_valid():
    filters = normalize_export_filters(
        {"date_from": "2026-02-03", "date_to": "2026-02-03"}
    )

    assert filters.date_from == "2026-02-03"
    assert filters.date_to == "2026-02-03"


def test_empty_range_is_rejected_before_enqueue():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(ExportFilterValidationError, match="date_from"):
        service.create_job(
            {"date_from": "2026-02-04", "date_to": "2026-02-03"}
        )

    assert queue.tasks == []


@pytest.mark.parametrize("field", ["date_from", "date_to"])
def test_invalid_dates_are_rejected_before_enqueue(field):
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(ExportFilterValidationError, match=field):
        service.create_job({field: "2026-99-01"})

    assert queue.tasks == []


@pytest.mark.parametrize("status", ["archived", "", "   "])
def test_unsupported_or_empty_status_is_rejected_before_enqueue(status):
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(ExportFilterValidationError, match="status"):
        service.create_job({"status": status})

    assert queue.tasks == []


def test_empty_workspace_is_rejected_before_enqueue():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(ExportFilterValidationError, match="workspace_id"):
        service.create_job({"workspace_id": "   "})

    assert queue.tasks == []


def test_valid_filters_are_persisted_normalized_in_queued_job():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    job = service.create_job(
        {
            "date_from": "2026-03-01",
            "date_to": "2026-03-31",
            "workspace_id": " workspace-2 ",
            "status": "FAILED",
        }
    )

    assert job.queue_task_id == "queued-1"
    assert job.filters.to_dict() == {
        "date_from": "2026-03-01",
        "date_to": "2026-03-31",
        "workspace_id": "workspace-2",
        "status": "failed",
    }
    assert queue.tasks == [
        {
            "task": {
                "type": "bulk_export",
                "job_id": job.job_id,
                "filters": job.filters.to_dict(),
                "created_at": job.created_at,
            },
            "queue": "exports",
            "priority": 0,
        }
    ]


def test_optional_filters_create_empty_normalized_filter_set():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    job = service.create_job({})

    assert job.filters.to_dict() == {}
    assert queue.tasks[0]["task"]["filters"] == {}
