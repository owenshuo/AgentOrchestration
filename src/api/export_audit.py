"""Export download audit trail helpers."""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ExportRecord:
    export_id: str
    content: bytes
    owner: str
    direct_token: Optional[str] = None


@dataclass(frozen=True)
class ExportAuditEvent:
    actor: str
    export_id: str
    timestamp: float
    result: str
    path: str


class ExportAccessError(Exception):
    def __init__(self, status_code: int, result: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.result = result
        self.detail = detail


class ExportDownloadService:
    def __init__(self):
        self._exports: Dict[str, ExportRecord] = {}
        self._direct_tokens: Dict[str, str] = {}
        self._audit_events: List[ExportAuditEvent] = []

    def register_export(
        self,
        export_id: str,
        content: bytes,
        owner: str,
        direct_token: Optional[str] = None,
    ) -> None:
        self._exports[export_id] = ExportRecord(
            export_id=export_id,
            content=content,
            owner=owner,
            direct_token=direct_token,
        )
        if direct_token:
            self._direct_tokens[direct_token] = export_id

    def download_for_actor(self, export_id: str, actor: str) -> bytes:
        record = self._exports.get(export_id)
        if not record:
            self._record(actor, export_id, "not_found", "api")
            raise ExportAccessError(404, "not_found", "Export not found")
        if record.owner != actor:
            self._record(actor, export_id, "forbidden", "api")
            raise ExportAccessError(403, "forbidden", "Export access denied")
        self._record(actor, export_id, "success", "api")
        return record.content

    def download_with_token(self, token: str, actor: str) -> bytes:
        export_id = self._direct_tokens.get(token)
        if not export_id:
            self._record(actor, "unknown", "not_found", "direct")
            raise ExportAccessError(404, "not_found", "Export link not found")

        record = self._exports.get(export_id)
        if not record:
            self._record(actor, export_id, "not_found", "direct")
            raise ExportAccessError(404, "not_found", "Export not found")

        self._record(actor, export_id, "success", "direct")
        return record.content

    def audit_events(self) -> List[ExportAuditEvent]:
        return list(self._audit_events)

    def reset(self) -> None:
        self._exports.clear()
        self._direct_tokens.clear()
        self._audit_events.clear()

    def _record(
        self,
        actor: str,
        export_id: str,
        result: str,
        path: str,
    ) -> None:
        self._audit_events.append(
            ExportAuditEvent(
                actor=actor,
                export_id=export_id,
                timestamp=time.time(),
                result=result,
                path=path,
            )
        )


export_downloads = ExportDownloadService()
