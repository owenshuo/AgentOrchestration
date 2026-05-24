import asyncio

import pytest

from src.sdk.agent import BaseAgent


class SetupFailureAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(agent_id="agent-1", name="setup-failure")
        self.resources_opened = 0
        self.cleanup_calls = 0

    async def setup(self) -> None:
        self.resources_opened += 1
        raise RuntimeError("setup failed after opening resource")

    async def handle_task(self, task):
        return task

    async def cleanup(self) -> None:
        self.cleanup_calls += 1
        self.resources_opened = 0


class StoppableAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(agent_id="agent-2", name="stoppable")
        self.setup_calls = 0
        self.cleanup_calls = 0

    async def setup(self) -> None:
        self.setup_calls += 1

    async def handle_task(self, task):
        return task

    async def cleanup(self) -> None:
        self.cleanup_calls += 1


def test_base_agent_cleans_up_after_setup_failure() -> None:
    agent = SetupFailureAgent()

    with pytest.raises(RuntimeError, match="setup failed"):
        asyncio.run(agent.run())

    assert agent.cleanup_calls == 1
    assert agent.resources_opened == 0


def test_base_agent_still_cleans_up_on_cancellation() -> None:
    async def run_and_cancel(agent: StoppableAgent) -> None:
        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0)
        task.cancel()
        await task

    agent = StoppableAgent()

    asyncio.run(run_and_cancel(agent))

    assert agent.setup_calls == 1
    assert agent.cleanup_calls == 1
