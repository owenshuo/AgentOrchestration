"""Temporary table retention metadata and cleanup helpers."""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class TemporaryTableError(ValueError):
    """Raised when temporary table metadata is invalid."""


@dataclass
class TemporaryTable:
    name: str
    owner: str
    purpose: str
    expires_at: float
    created_at: float
    table_id: str = field(default_factory=lambda: str(uuid4()))
    row_count: int = 0
    is_helper: bool = True

    def retention_labels(self) -> Dict[str, Any]:
        return {
            "owner": self.owner,
            "purpose": self.purpose,
            "expires_at": self.expires_at,
            "temporary": True,
        }


class TemporaryTableRegistry:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._tables: Dict[str, TemporaryTable] = {}
        self.audit_records: List[Dict[str, Any]] = []

    def create_helper_table(
        self,
        name: str,
        *,
        owner: str,
        purpose: str,
        ttl_seconds: float,
        row_count: int = 0,
    ) -> TemporaryTable:
        name = self._require_text("name", name)
        owner = self._require_text("owner", owner)
        purpose = self._require_text("purpose", purpose)
        if ttl_seconds <= 0:
            raise TemporaryTableError("ttl_seconds must be positive")
        if row_count < 0:
            raise TemporaryTableError("row_count must be non-negative")

        now = self._clock()
        table = TemporaryTable(
            name=name,
            owner=owner,
            purpose=purpose,
            expires_at=now + ttl_seconds,
            created_at=now,
            row_count=row_count,
        )
        self._tables[table.table_id] = table
        self._record("created", table, expired=False)
        return table

    def report(self) -> Dict[str, List[Dict[str, Any]]]:
        active: List[Dict[str, Any]] = []
        expired: List[Dict[str, Any]] = []
        now = self._clock()
        for table in self._tables.values():
            row = self._public_row(table)
            if table.expires_at <= now:
                expired.append(row)
            else:
                active.append(row)
        return {
            "active_temporary_tables": active,
            "expired_temporary_tables": expired,
        }

    def cleanup_expired(
        self,
        safety_check: Optional[Callable[[TemporaryTable], bool]] = None,
    ) -> List[str]:
        removed: List[str] = []
        now = self._clock()
        for table_id, table in list(self._tables.items()):
            if table.expires_at > now:
                continue
            if not table.is_helper:
                self._record(
                    "skipped",
                    table,
                    expired=True,
                    reason="not_helper",
                )
                continue
            if safety_check and not safety_check(table):
                self._record(
                    "skipped",
                    table,
                    expired=True,
                    reason="safety_check_failed",
                )
                continue
            removed.append(table_id)
            del self._tables[table_id]
            self._record("removed", table, expired=True)
        return removed

    def _public_row(self, table: TemporaryTable) -> Dict[str, Any]:
        return {
            "table_id": table.table_id,
            "name": table.name,
            "owner": table.owner,
            "purpose": table.purpose,
            "expires_at": table.expires_at,
            "row_count": table.row_count,
        }

    def _record(
        self,
        decision: str,
        table: TemporaryTable,
        *,
        expired: bool,
        reason: Optional[str] = None,
    ) -> None:
        record = {
            "decision": decision,
            "table_id": table.table_id,
            "name": table.name,
            "owner": table.owner,
            "purpose": table.purpose,
            "expired": expired,
        }
        if reason:
            record["reason"] = reason
        self.audit_records.append(record)

    @staticmethod
    def _require_text(field_name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TemporaryTableError(f"{field_name} is required")
        return value.strip()
