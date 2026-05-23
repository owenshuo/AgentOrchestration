"""Retention-aware quarantine storage for invalid validation payloads."""

import copy
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional


DEFAULT_REDACTED_FIELDS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}


@dataclass
class QuarantineRecord:
    record_id: str
    reason: str
    payload: Dict[str, Any]
    redacted_payload: Dict[str, Any]
    created_at: float
    expires_at: float
    access_token: str

    def redacted_view(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "reason": self.reason,
            "payload": copy.deepcopy(self.redacted_payload),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    def raw_view(self) -> Dict[str, Any]:
        view = self.redacted_view()
        view["payload"] = copy.deepcopy(self.payload)
        return view


class ValidationQuarantineStore:
    """Stores failed validation payloads with TTL and redacted access."""

    def __init__(
        self,
        ttl_seconds: float = 7 * 24 * 60 * 60,
        clock: Callable[[], float] = time.time,
        redacted_fields: Optional[set[str]] = None,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._redacted_fields = {
            field.lower() for field in (
                redacted_fields or DEFAULT_REDACTED_FIELDS
            )
        }
        self._records: Dict[str, QuarantineRecord] = {}
        self._audit_records: List[Dict[str, Any]] = []

    def add(self, payload: Mapping[str, Any], reason: str) -> QuarantineRecord:
        now = self._clock()
        record = QuarantineRecord(
            record_id=str(uuid.uuid4()),
            reason=reason,
            payload=copy.deepcopy(dict(payload)),
            redacted_payload=self._redact(payload),
            created_at=now,
            expires_at=now + self._ttl_seconds,
            access_token=str(uuid.uuid4()),
        )
        self._records[record.record_id] = record
        self._audit("stored", record.record_id, reason=reason)
        return record

    def get(
        self,
        record_id: str,
        *,
        include_payload: bool = False,
        access_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self.cleanup_expired()
        record = self._records.get(record_id)
        if record is None:
            return None

        if include_payload:
            if access_token != record.access_token:
                self._audit("raw_access_denied", record_id)
                raise PermissionError("raw quarantine payload access denied")
            self._audit("raw_accessed", record_id)
            return record.raw_view()

        return record.redacted_view()

    def cleanup_expired(self) -> int:
        now = self._clock()
        expired = [
            record_id
            for record_id, record in self._records.items()
            if record.expires_at <= now
        ]
        for record_id in expired:
            self._records.pop(record_id, None)
            self._audit("expired", record_id)
        return len(expired)

    def list_records(self) -> List[Dict[str, Any]]:
        self.cleanup_expired()
        return [
            record.redacted_view()
            for record in self._records.values()
        ]

    @property
    def audit_records(self) -> List[Dict[str, Any]]:
        return list(self._audit_records)

    def _redact(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        redacted: Dict[str, Any] = {}
        for key, value in payload.items():
            if key.lower() in self._redacted_fields:
                redacted[key] = "[REDACTED]"
            elif isinstance(value, Mapping):
                redacted[key] = self._redact(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self._redact(item) if isinstance(item, Mapping) else item
                    for item in value
                ]
            else:
                redacted[key] = copy.deepcopy(value)
        return redacted

    def _audit(
        self, action: str, record_id: str, **metadata: Any
    ) -> None:
        record = {
            "component": "validation_quarantine",
            "action": action,
            "record_id": record_id,
        }
        record.update(metadata)
        self._audit_records.append(record)
