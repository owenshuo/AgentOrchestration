import asyncio

from src.agent.registry import AgentStatus
from src.orchestrator.engine import OrchestrationEngine


def test_engine_does_not_execute_disabled_agent_from_cached_lookup():
    errors = []
    completed = []

    async def on_error(task, error):
        errors.append((task, error))

    async def on_complete(task, result):
        completed.append((task, result))

    async def run():
        engine = OrchestrationEngine()
        agent_id = engine.registry.register("test-agent", "worker.processor")
        assert engine.registry.update_status(agent_id, AgentStatus.RUNNING)
        assert engine.registry.resolve(agent_id) is not None
        assert engine.registry.update_status(agent_id, AgentStatus.STOPPED)
        engine.register_hook("on_error", on_error)
        engine.register_hook("post_execute", on_complete)

        await engine._execute_task({"id": "task-1", "target_agent": agent_id})
        return agent_id, engine

    agent_id, engine = asyncio.run(run())

    assert not completed
    assert len(errors) == 1
    assert errors[0][0]["id"] == "task-1"
    assert "unavailable" in str(errors[0][1])
    assert engine.registry.get(agent_id)["status"] == "stopped"
