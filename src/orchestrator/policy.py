"""Fail-closed policy runtime for orchestrator transitions."""

import inspect
from dataclasses import dataclass
from typing import Any, Dict, Optional


class PolicyUnavailableError(RuntimeError):
    """Raised when no policy decision can be produced."""


class PolicyRejectedError(RuntimeError):
    """Raised when policy denies a transition."""


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = "allowed"


class AllowAllPolicyEngine:
    async def authorize(
        self,
        transition: Dict[str, Any],
        task: Dict[str, Any],
        agent: Optional[Dict[str, Any]],
    ) -> PolicyDecision:
        return PolicyDecision(True)


class PolicyRuntime:
    def __init__(self, engine: Optional[Any]):
        self.engine = engine
        self.audit_records = []

    async def authorize(
        self,
        transition: Dict[str, Any],
        task: Dict[str, Any],
        agent: Optional[Dict[str, Any]],
    ) -> PolicyDecision:
        if self.engine is None:
            return self._deny_unavailable(transition, task)

        if hasattr(self.engine, "authorize"):
            decision = self.engine.authorize(transition, task, agent)
        elif callable(self.engine):
            decision = self.engine(transition, task, agent)
        else:
            return self._deny_unavailable(transition, task)

        if inspect.isawaitable(decision):
            decision = await decision
        decision = self._coerce_decision(decision)
        self._record(transition, task, decision)
        if not decision.allowed:
            raise PolicyRejectedError(decision.reason)
        return decision

    def _deny_unavailable(
        self,
        transition: Dict[str, Any],
        task: Dict[str, Any],
    ) -> PolicyDecision:
        decision = PolicyDecision(False, "policy_unavailable")
        self._record(transition, task, decision)
        raise PolicyUnavailableError(decision.reason)

    @staticmethod
    def _coerce_decision(decision: Any) -> PolicyDecision:
        if isinstance(decision, PolicyDecision):
            return decision
        if isinstance(decision, bool):
            reason = "allowed" if decision else "denied"
            return PolicyDecision(decision, reason)
        if isinstance(decision, dict):
            return PolicyDecision(
                bool(decision.get("allowed")),
                str(decision.get("reason") or "denied"),
            )
        raise PolicyUnavailableError("invalid_policy_decision")

    def _record(
        self,
        transition: Dict[str, Any],
        task: Dict[str, Any],
        decision: PolicyDecision,
    ) -> None:
        self.audit_records.append(
            {
                "task_id": task.get("id"),
                "transition": transition.get("name"),
                "allowed": decision.allowed,
                "reason": decision.reason,
            }
        )
