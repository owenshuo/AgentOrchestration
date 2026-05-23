import asyncio
import time

import pytest

from src.agent.executor import AgentExecutor


async def _handler(agent_id, task):
    return {"agent_id": agent_id, "task_id": task["id"]}


async def _failing_handler(agent_id, task):
    raise RuntimeError("boom")


def test_executor_rejects_invalid_result_limits():
    with pytest.raises(ValueError):
        AgentExecutor(max_results=0)
    with pytest.raises(ValueError):
        AgentExecutor(result_ttl=0)


def test_executor_prunes_oldest_results_by_max_count():
    async def scenario():
        executor = AgentExecutor(max_results=3, result_ttl=None)
        execution_ids = []
        for index in range(5):
            execution_id = await executor.execute(
                "agent-1", {"id": f"task-{index}"}, _handler
            )
            execution_ids.append(execution_id)

        return executor, execution_ids

    executor, execution_ids = asyncio.run(scenario())

    assert executor.result_count() == 3
    assert executor.get_result(execution_ids[0]) is None
    assert executor.get_result(execution_ids[1]) is None
    assert executor.get_result(execution_ids[2]) is not None
    assert executor.get_result(execution_ids[4]) is not None


def test_executor_prunes_results_by_ttl_on_read():
    async def scenario():
        executor = AgentExecutor(max_results=10, result_ttl=0.01)
        execution_id = await executor.execute(
            "agent-1", {"id": "task-1"}, _handler
        )
        return executor, execution_id

    executor, execution_id = asyncio.run(scenario())

    assert executor.get_result(execution_id) is not None
    time.sleep(0.02)
    assert executor.get_result(execution_id) is None
    assert executor.result_count() == 0


def test_executor_prunes_error_results_with_same_bounds():
    async def scenario():
        executor = AgentExecutor(max_results=1, result_ttl=None)
        first = await executor.execute(
            "agent-1", {"id": "first"}, _failing_handler
        )
        second = await executor.execute(
            "agent-1", {"id": "second"}, _handler
        )
        return executor, first, second

    executor, first, second = asyncio.run(scenario())

    assert executor.result_count() == 1
    assert executor.get_result(first) is None
    assert executor.get_result(second) is not None


def test_executor_shutdown_clears_stored_results():
    async def scenario():
        executor = AgentExecutor(max_results=10, result_ttl=None)
        execution_id = await executor.execute(
            "agent-1", {"id": "task-1"}, _handler
        )
        assert executor.get_result(execution_id) is not None
        await executor.shutdown()
        return executor

    executor = asyncio.run(scenario())

    assert executor.result_count() == 0
