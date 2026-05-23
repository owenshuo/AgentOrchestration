"""Validate bulk export filters before job creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, Mapping, Optional, Protocol
from uuid import uuid4


SUPPORTED_EXPORT_STATUSES = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)


class ExportFilterValidationError(ValueError):
    """Raised when export filters are invalid before enqueue."""


class ExportQueue(Protocol):
    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        """Persist a queued task and return the queue task id."""


@dataclass(frozen=True)
class NormalizedExportFilters:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    workspace_id: Optional[str] = None
    status: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        return {
            key: value
            for key, value in {
                "date_from": self.date_from,
                "date_to": self.date_to,
                "workspace_id": self.workspace_id,
                "status": self.status,
            }.items()
            if value is not None
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ExportJob:
    job_id: str
    filters: NormalizedExportFilters
    queue_task_id: str
    created_at: str = field(default_factory=_utc_now_iso)

    def to_task(self) -> Dict:
        return {
            "type": "bulk_export",
            "job_id": self.job_id,
            "filters": self.filters.to_dict(),
            "created_at": self.created_at,
        }

    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "queue_task_id": self.queue_task_id,
            "filters": self.filters.to_dict(),
            "created_at": self.created_at,
        }


class ExportJobService:
    """Validate filters synchronously, then enqueue normalized jobs."""

    def __init__(self, queue: ExportQueue, queue_name: str = "exports"):
        self.queue = queue
        self.queue_name = queue_name

    def create_job(self, raw_filters: Mapping[str, object]) -> ExportJob:
        filters = normalize_export_filters(raw_filters)
        job_id = str(uuid4())
        created_at = _utc_now_iso()
        task = {
            "type": "bulk_export",
            "job_id": job_id,
            "filters": filters.to_dict(),
            "created_at": created_at,
        }
        queue_task_id = self.queue.enqueue(task, queue=self.queue_name)
        return ExportJob(
            job_id=job_id,
            filters=filters,
            queue_task_id=queue_task_id,
            created_at=created_at,
        )


def normalize_export_filters(
    raw_filters: Mapping[str, object],
) -> NormalizedExportFilters:
    date_from = _normalize_date(raw_filters.get("date_from"), "date_from")
    date_to = _normalize_date(raw_filters.get("date_to"), "date_to")
    if date_from and date_to and date_from > date_to:
        raise ExportFilterValidationError(
            "date_from must be on or before date_to"
        )

    workspace_id = _normalize_workspace(raw_filters.get("workspace_id"))
    status = _normalize_status(raw_filters.get("status"))
    return NormalizedExportFilters(
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        workspace_id=workspace_id,
        status=status,
    )


def _normalize_date(value: object, field_name: str) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ExportFilterValidationError(
            f"{field_name} must be an ISO date string"
        )
    stripped = value.strip()
    if not stripped:
        raise ExportFilterValidationError(f"{field_name} cannot be empty")
    try:
        return date.fromisoformat(stripped)
    except ValueError as error:
        raise ExportFilterValidationError(
            f"{field_name} must use YYYY-MM-DD format"
        ) from error


def _normalize_workspace(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExportFilterValidationError("workspace_id must be a string")
    workspace_id = value.strip()
    if not workspace_id:
        raise ExportFilterValidationError("workspace_id cannot be empty")
    return workspace_id


def _normalize_status(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExportFilterValidationError("status must be a string")
    status = value.strip().lower()
    if not status:
        raise ExportFilterValidationError("status cannot be empty")
    if status not in SUPPORTED_EXPORT_STATUSES:
        allowed = ", ".join(sorted(SUPPORTED_EXPORT_STATUSES))
        raise ExportFilterValidationError(
            f"unsupported status {value!r}; expected one of: {allowed}"
        )
    return status
