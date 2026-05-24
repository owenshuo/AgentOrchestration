import asyncio

from src.orchestrator.events import RunEvent, RunEventBus
from src.orchestrator.engine import OrchestrationEngine


def run(coro):
    return asyncio.run(coro)


class TestRunEventBus:
    def test_drops_out_of_order_events(self):
        async def scenario():
            bus = RunEventBus()
            await bus.publish(RunEvent("run-1", "worker", 2, "running"))
            record, changed = await bus.publish(
                RunEvent("run-1", "worker", 1, "queued")
            )
            return record, changed

        record, changed = run(scenario())
        assert not changed
        assert record.sequence == 2
        assert record.state == "running"

    def test_deduplicates_retried_event(self):
        async def scenario():
            bus = RunEventBus()
            first, first_changed = await bus.publish(
                RunEvent("run-1", "scheduler", 1, "running")
            )
            second, second_changed = await bus.publish(
                RunEvent("run-1", "scheduler", 1, "running")
            )
            return first, first_changed, second, second_changed

        first, first_changed, second, second_changed = run(scenario())
        assert first_changed
        assert not second_changed
        assert second == first

    def test_terminal_event_is_durable(self):
        async def scenario():
            bus = RunEventBus()
            await bus.publish(RunEvent("run-1", "worker", 1, "running"))
            await bus.publish(RunEvent("run-1", "worker", 2, "completed"))
            record, changed = await bus.publish(
                RunEvent("run-1", "retry", 3, "failed")
            )
            return record, changed

        record, changed = run(scenario())
        assert not changed
        assert record.state == "completed"
        assert record.sequence == 2

    def test_concurrent_producers_keep_highest_fresh_transition(self):
        async def scenario():
            bus = RunEventBus()
            events = [
                RunEvent("run-1", "worker-a", 1, "running"),
                RunEvent("run-1", "worker-b", 2, "checkpointed"),
                RunEvent("run-1", "scheduler", 3, "completed"),
                RunEvent("run-1", "worker-a", 2, "running"),
            ]
            await asyncio.gather(*(bus.publish(event) for event in events))
            return await bus.snapshot("run-1")

        record = run(scenario())
        assert record.state == "completed"
        assert record.sequence == 3

    def test_newer_attempt_can_replace_non_terminal_attempt(self):
        async def scenario():
            bus = RunEventBus()
            await bus.publish(
                RunEvent("run-1", "worker", 5, "running", attempt=1)
            )
            record, changed = await bus.publish(
                RunEvent("run-1", "worker", 1, "running", attempt=2)
            )
            return record, changed

        record, changed = run(scenario())
        assert changed
        assert record.attempt == 2
        assert record.sequence == 1


class TestOrchestrationEngineEventOrdering:
    def test_engine_records_one_terminal_success(self):
        async def scenario():
            engine = OrchestrationEngine()
            agent_id = engine.registry.register("runner", "test.runner")
            task_id = engine.scheduler.enqueue(
                {"target_agent": agent_id, "type": "test"}
            )
            task = await engine.scheduler.dequeue()

            await engine._execute_task(task)
            result = await engine._publish_task_event(
                task,
                "failed",
                sequence=3,
                payload={"error": "late retry"},
            )
            duplicate_record, duplicate_changed = result
            return (
                task_id,
                task,
                duplicate_record,
                duplicate_changed,
                engine.scheduler._in_flight,
            )

        task_id, task, record, changed, in_flight = run(scenario())
        assert task["id"] == task_id
        assert not changed
        assert record.state == "completed"
        assert task_id not in in_flight

    def test_engine_failure_is_durable_against_late_success(self):
        async def scenario():
            engine = OrchestrationEngine()
            task_id = engine.scheduler.enqueue(
                {"target_agent": "missing", "type": "test"}
            )
            task = await engine.scheduler.dequeue()

            await engine._execute_task(task)
            record, changed = await engine._publish_task_event(
                task, "completed", sequence=3
            )
            return task_id, record, changed, engine.scheduler._in_flight

        task_id, record, changed, in_flight = run(scenario())
        assert not changed
        assert record.state == "failed"
        assert task_id not in in_flight
