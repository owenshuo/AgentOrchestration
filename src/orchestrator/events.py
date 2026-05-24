"""Run event ordering and idempotency guards for orchestration runtime."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple

TERMINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class RunEvent:
    """A state transition produced by an async runtime component."""

    run_id: str
    producer_id: str
    sequence: int
    state: str
    attempt: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunEventRecord:
    """Latest accepted state for a run."""

    run_id: str
    producer_id: str
    sequence: int
    state: str
    attempt: int
    payload: Dict[str, Any] = field(default_factory=dict)


class RunEventBus:
    """Accepts only fresh run events and drops stale retry noise.

    Multiple runtime producers can race to publish the same run state. This
    store keeps the highest accepted attempt/sequence per run and treats
    terminal states as durable one-shot outcomes.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._latest: Dict[str, RunEventRecord] = {}
        self._seen: Set[Tuple[str, str, int, int]] = set()

    async def publish(self, event: RunEvent) -> Tuple[RunEventRecord, bool]:
        """Publish an event and report whether it changed state."""
        if event.sequence < 0:
            raise ValueError("event sequence must be non-negative")
        if event.attempt < 0:
            raise ValueError("event attempt must be non-negative")

        key = (event.run_id, event.producer_id, event.attempt, event.sequence)
        async with self._lock:
            current = self._latest.get(event.run_id)
            if key in self._seen:
                return current or self._record_from_event(event), False

            if current and not self._is_fresh(event, current):
                self._seen.add(key)
                return current, False

            record = self._record_from_event(event)
            self._latest[event.run_id] = record
            self._seen.add(key)
            return record, True

    async def snapshot(self, run_id: str) -> Optional[RunEventRecord]:
        async with self._lock:
            return self._latest.get(run_id)

    def _is_fresh(self, event: RunEvent, current: RunEventRecord) -> bool:
        if current.state in TERMINAL_STATES:
            return False
        if event.attempt != current.attempt:
            return event.attempt > current.attempt
        return event.sequence > current.sequence

    def _record_from_event(self, event: RunEvent) -> RunEventRecord:
        return RunEventRecord(
            run_id=event.run_id,
            producer_id=event.producer_id,
            sequence=event.sequence,
            state=event.state,
            attempt=event.attempt,
            payload=dict(event.payload),
        )
