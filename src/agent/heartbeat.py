"""Heartbeat state guard for worker run lifecycle."""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Dict, List, Optional


class RunState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {
    RunState.COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED,
}


@dataclass(frozen=True)
class HeartbeatResult:
    accepted: bool
    run_id: str
    state: RunState
    reason: str


class HeartbeatMonitor:
    def __init__(self, stale_after_seconds: float = 60.0):
        self.stale_after_seconds = stale_after_seconds
        self._states: Dict[str, RunState] = {}
        self._terminal_outcomes: Dict[str, RunState] = {}
        self._locks: Dict[str, float] = {}
        self.audit_log: List[Dict[str, str]] = []

    def start_run(self, run_id: str, now: Optional[float] = None) -> bool:
        state = self._states.get(run_id)
        if state in TERMINAL_STATES:
            self._record(run_id, state, "start_ignored_terminal")
            return False
        if run_id in self._locks:
            self._record(
                run_id, state or RunState.RUNNING, "start_ignored_locked"
            )
            return False

        self._states[run_id] = RunState.RUNNING
        self._locks[run_id] = self._timestamp(now)
        self._record(run_id, RunState.RUNNING, "run_started")
        return True

    def heartbeat(
        self, run_id: str, now: Optional[float] = None
    ) -> HeartbeatResult:
        state = self._states.get(run_id)
        if state in TERMINAL_STATES or run_id in self._terminal_outcomes:
            terminal_state = self._terminal_outcomes.get(run_id, state)
            self._locks.pop(run_id, None)
            self._record(run_id, terminal_state, "heartbeat_ignored_terminal")
            return HeartbeatResult(
                accepted=False,
                run_id=run_id,
                state=terminal_state,
                reason="terminal_state",
            )

        self._states[run_id] = RunState.RUNNING
        self._locks[run_id] = self._timestamp(now)
        self._record(run_id, RunState.RUNNING, "heartbeat_accepted")
        return HeartbeatResult(
            accepted=True,
            run_id=run_id,
            state=RunState.RUNNING,
            reason="accepted",
        )

    def complete_run(
        self, run_id: str, state: RunState = RunState.COMPLETED
    ) -> bool:
        if state not in TERMINAL_STATES:
            raise ValueError("run completion state must be terminal")
        existing_terminal = self._terminal_outcomes.get(run_id)
        if existing_terminal:
            self._record(
                run_id, existing_terminal, "terminal_outcome_preserved"
            )
            return False

        self._states[run_id] = state
        self._terminal_outcomes[run_id] = state
        self._locks.pop(run_id, None)
        self._record(run_id, state, "terminal_outcome_recorded")
        return True

    def sweep_stale_locks(self, now: Optional[float] = None) -> List[str]:
        current_time = self._timestamp(now)
        stale = [
            run_id
            for run_id, locked_at in self._locks.items()
            if current_time - locked_at >= self.stale_after_seconds
            and self._states.get(run_id) not in TERMINAL_STATES
        ]
        for run_id in stale:
            self._locks.pop(run_id, None)
            self._record(run_id, self._states[run_id], "stale_lock_released")
        return stale

    def get_state(self, run_id: str) -> Optional[RunState]:
        return self._states.get(run_id)

    def has_lock(self, run_id: str) -> bool:
        return run_id in self._locks

    def _record(self, run_id: str, state: RunState, event: str) -> None:
        self.audit_log.append(
            {"run_id": run_id, "state": state.value, "event": event}
        )

    def _timestamp(self, now: Optional[float]) -> float:
        return time.time() if now is None else now
