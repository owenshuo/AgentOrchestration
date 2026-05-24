import asyncio

from src.agent.registry import AgentStatus
from src.orchestrator.engine import (
    OrchestrationEngine,
    RunHeartbeatMonitor,
    RunState,
)


def test_worker_heartbeat_does_not_revive_completed_run():
    monitor = RunHeartbeatMonitor()

    assert monitor.begin("run-1")
    assert monitor.record_heartbeat("run-1", "worker-a", timestamp=10.0)
    assert monitor.complete("run-1")

    assert not monitor.record_heartbeat("run-1", "worker-a", timestamp=11.0)
    assert monitor.state("run-1") is RunState.COMPLETED
    assert monitor.last_heartbeat("run-1") == {
        "worker_id": "worker-a",
        "timestamp": 10.0,
    }
    assert monitor.decisions()[-1] == {
        "run_id": "run-1",
        "decision": "heartbeat_rejected_terminal",
        "state": "completed",
        "worker_id": "worker-a",
    }


def test_terminal_outcome_is_idempotent_and_not_overwritten():
    monitor = RunHeartbeatMonitor()

    assert monitor.begin("run-2")
    assert monitor.fail("run-2")

    assert monitor.complete("run-2") is False
    assert monitor.cancel("run-2") is False
    assert monitor.state("run-2") is RunState.FAILED
    assert [d["decision"] for d in monitor.decisions()[-2:]] == [
        "complete_rejected_terminal",
        "cancel_rejected_terminal",
    ]


def test_engine_persists_completed_run_before_late_heartbeat():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("worker", "worker.default")
    task = {"id": "task-1", "target_agent": agent_id}

    async def run_agent(agent, task_payload):
        return {"status": "completed"}

    engine._run_agent_task = run_agent

    asyncio.run(engine._execute_task(task))

    assert engine.heartbeat_monitor.state("task-1") is RunState.COMPLETED
    assert not engine.heartbeat_monitor.record_heartbeat("task-1", "worker-1")
    assert engine.heartbeat_monitor.state("task-1") is RunState.COMPLETED
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PAUSED.value
