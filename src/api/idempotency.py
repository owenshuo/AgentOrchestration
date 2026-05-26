"""Idempotency guards for destructive API actions."""

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for a different request."""


@dataclass
class IdempotencyRecord:
    fingerprint: str
    response: Dict[str, Any]
    created_at: float


class DestructiveActionIdempotencyStore:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        ttl: float = 300,
    ):
        self._clock = clock
        self.ttl = ttl
        self._records: Dict[str, IdempotencyRecord] = {}
        self._audit_events: List[Dict[str, Any]] = []

    def execute(
        self,
        key: Optional[str],
        fingerprint: str,
        action: Callable[[], Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], bool]:
        if not key:
            return action(), False
        self._expire_old()
        existing = self._records.get(key)
        if existing:
            if existing.fingerprint != fingerprint:
                self._audit("conflict", key, fingerprint)
                raise IdempotencyConflictError("idempotency key conflict")
            self._audit("replayed", key, fingerprint)
            return dict(existing.response), True

        response = action()
        self._records[key] = IdempotencyRecord(
            fingerprint=fingerprint,
            response=dict(response),
            created_at=self._clock(),
        )
        self._audit("stored", key, fingerprint)
        return response, False

    def reset(self) -> None:
        self._records.clear()
        self._audit_events.clear()

    def audit_report(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def _expire_old(self) -> None:
        now = self._clock()
        expired_keys = [
            key
            for key, record in self._records.items()
            if now - record.created_at >= self.ttl
        ]
        for key in expired_keys:
            self._records.pop(key, None)
            self._audit("expired", key, "")

    def _audit(self, action: str, key: str, fingerprint: str) -> None:
        self._audit_events.append(
            {
                "action": action,
                "key_hash": str(abs(hash(key))),
                "fingerprint": fingerprint,
                "timestamp": self._clock(),
            }
        )
