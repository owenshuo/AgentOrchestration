"""Trace aggregation runtime with bounded memory accounting."""

import json
import threading
import time
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class TraceOutcome(Enum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TraceMemoryLimitExceeded(RuntimeError):
    """Raised when trace aggregation would exceed its memory budget."""


class TraceAggregationRuntime:
    def __init__(self, max_bytes: int = 1024 * 1024):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._terminal_outcomes: Dict[str, Dict[str, Any]] = {}

    def get_outcome(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            outcome = self._terminal_outcomes.get(run_id)
            return dict(outcome) if outcome else None

    def cancel(self, run_id: str, reason: str = "cancelled") -> Dict[str, Any]:
        with self._lock:
            existing = self._terminal_outcomes.get(run_id)
            if existing:
                return dict(existing)
            outcome = self._record_terminal_outcome(
                run_id,
                TraceOutcome.CANCELLED,
                reason=reason,
                bytes_used=0,
            )
            return dict(outcome)

    def aggregate(
        self,
        run_id: str,
        events: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        with self._lock:
            existing = self._terminal_outcomes.get(run_id)
            if existing:
                if existing["status"] == TraceOutcome.COMPLETED.value:
                    return dict(existing)
                raise TraceMemoryLimitExceeded(existing["reason"])

            bytes_used = 0
            event_count = 0
            aggregated: List[Dict[str, Any]] = []
            for event in events:
                event_size = self._estimate_event_size(event)
                next_bytes = bytes_used + event_size
                if next_bytes > self.max_bytes:
                    outcome = self._record_terminal_outcome(
                        run_id,
                        TraceOutcome.REJECTED,
                        reason="trace aggregation memory limit exceeded",
                        bytes_used=bytes_used,
                        event_count=event_count,
                    )
                    raise TraceMemoryLimitExceeded(outcome["reason"])
                aggregated.append(dict(event))
                bytes_used = next_bytes
                event_count += 1

            outcome = self._record_terminal_outcome(
                run_id,
                TraceOutcome.COMPLETED,
                reason="completed",
                bytes_used=bytes_used,
                event_count=event_count,
                events=aggregated,
            )
            return dict(outcome)

    def _record_terminal_outcome(
        self,
        run_id: str,
        status: TraceOutcome,
        *,
        reason: str,
        bytes_used: int,
        event_count: int = 0,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        outcome = {
            "run_id": run_id,
            "status": status.value,
            "reason": reason,
            "bytes_used": bytes_used,
            "event_count": event_count,
            "recorded_at": time.time(),
        }
        if events is not None:
            outcome["events"] = events
        self._terminal_outcomes[run_id] = outcome
        return outcome

    @staticmethod
    def _estimate_event_size(event: Dict[str, Any]) -> int:
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        return len(payload.encode("utf-8"))
