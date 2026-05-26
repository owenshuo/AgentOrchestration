import asyncio

from src.agent.registry import AgentStatus
from src.orchestrator.engine import OrchestrationEngine
from src.orchestrator.policy import PolicyDecision


class DenyPolicy:
    async def authorize(self, transition, task, agent):
        return PolicyDecision(False, "blocked")


def _task(agent_id, task_id="task-1"):
    return {"id": task_id, "target_agent": agent_id}


_DEFAULT = object()


def _engine(policy_engine=_DEFAULT):
    if policy_engine is _DEFAULT:
        engine = OrchestrationEngine()
    else:
        engine = OrchestrationEngine(policy_engine=policy_engine)
    agent_id = engine.registry.register("agent", "worker")
    return engine, agent_id


def test_policy_unavailable_fails_closed_before_side_effects():
    engine, agent_id = _engine(policy_engine=None)
    hooks = []
    engine.register_hook("pre_execute", lambda task: hooks.append(task["id"]))

    asyncio.run(engine._execute_task(_task(agent_id)))

    outcome = engine.get_task_outcome("task-1")
    agent = engine.registry.get(agent_id)
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "policy_unavailable"
    assert agent["status"] == AgentStatus.PENDING.value
    assert hooks == []
    assert engine.policy_runtime.audit_records[-1]["reason"] == (
        "policy_unavailable"
    )


def test_policy_rejection_records_single_terminal_outcome():
    engine, agent_id = _engine(policy_engine=DenyPolicy())

    asyncio.run(engine._execute_task(_task(agent_id)))
    asyncio.run(engine._execute_task(_task(agent_id)))

    outcome = engine.get_task_outcome("task-1")
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "policy_rejected"
    assert len(engine._terminal_outcomes) == 1
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value


def test_allowed_policy_records_completion_once(monkeypatch):
    engine, agent_id = _engine()

    async def fake_run(agent, task):
        return {"status": "completed", "task_id": task["id"]}

    monkeypatch.setattr(engine, "_run_agent_task", fake_run)

    asyncio.run(engine._execute_task(_task(agent_id)))
    asyncio.run(engine._execute_task(_task(agent_id)))

    outcome = engine.get_task_outcome("task-1")
    assert outcome["status"] == "completed"
    assert outcome["result"] == {
        "status": "completed",
        "task_id": "task-1",
    }
    assert len(engine._terminal_outcomes) == 1
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PAUSED.value


def test_callable_policy_dict_decision_is_supported(monkeypatch):
    def policy(transition, task, agent):
        return {"allowed": True, "reason": "ok"}

    engine, agent_id = _engine(policy_engine=policy)

    async def fake_run(agent, task):
        return {"status": "completed"}

    monkeypatch.setattr(engine, "_run_agent_task", fake_run)

    asyncio.run(engine._execute_task(_task(agent_id)))

    assert engine.get_task_outcome("task-1")["status"] == "completed"
    assert engine.policy_runtime.audit_records[-1]["allowed"] is True


def test_policy_runtime_rejects_invalid_engine_without_dispatch():
    engine, agent_id = _engine(policy_engine=object())

    asyncio.run(engine._execute_task(_task(agent_id)))

    outcome = engine.get_task_outcome("task-1")
    assert outcome["reason"] == "policy_unavailable"
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value
