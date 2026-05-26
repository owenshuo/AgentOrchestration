"""Run event stream service with bounded pagination."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException


DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_PAGINATION_WINDOW = 5000


EventLookup = Callable[[str, int, int], List[Dict[str, Any]]]
RunAuthorizer = Callable[[str, str], bool]


@dataclass
class RunEventService:
    lookup_events: EventLookup
    can_access_run: RunAuthorizer

    def list_events(
        self,
        *,
        workspace_id: str,
        run_id: str,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = _validate_pagination(limit, offset)
        if not workspace_id.strip() or not run_id.strip():
            raise HTTPException(
                status_code=400,
                detail="workspace_id and run_id are required",
            )
        if not self.can_access_run(workspace_id, run_id):
            raise HTTPException(status_code=403, detail="Run access denied")

        events = self.lookup_events(run_id, limit, offset)
        return {
            "run_id": run_id,
            "workspace_id": workspace_id,
            "limit": limit,
            "offset": offset,
            "events": events,
        }


def _validate_pagination(limit: int, offset: int) -> tuple[int, int]:
    if not isinstance(limit, int) or not isinstance(offset, int):
        raise HTTPException(
            status_code=400,
            detail="limit and offset must be integers",
        )
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {MAX_LIMIT}",
        )
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if offset + limit > MAX_PAGINATION_WINDOW:
        raise HTTPException(
            status_code=416,
            detail=(
                "pagination window exceeds "
                f"{MAX_PAGINATION_WINDOW} events"
            ),
        )
    return limit, offset


class InMemoryRunEventStore:
    def __init__(self) -> None:
        self._events: Dict[str, List[Dict[str, Any]]] = {}
        self._run_workspaces: Dict[str, str] = {}

    def add_run(
        self,
        workspace_id: str,
        run_id: str,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._run_workspaces[run_id] = workspace_id
        self._events[run_id] = list(events or [])

    def can_access_run(self, workspace_id: str, run_id: str) -> bool:
        return self._run_workspaces.get(run_id) == workspace_id

    def lookup_events(
        self,
        run_id: str,
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        return self._events.get(run_id, [])[offset:offset + limit]


store = InMemoryRunEventStore()
service = RunEventService(store.lookup_events, store.can_access_run)
