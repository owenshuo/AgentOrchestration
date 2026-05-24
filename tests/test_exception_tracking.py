import asyncio
import json
import logging

from src.agent.executor import AgentExecutor
from src.common.exception_tracking import (
    build_exception_event,
    sanitize_exception_context,
)
from src.common.logging import StructuredFormatter
from src.orchestrator.engine import OrchestrationEngine


RAW_SECRET = "card_4111111111111111"


def test_sanitizer_drops_nested_payload_and_local_capture_values():
    context = {
        "task_id": "task-123",
        "component": "executor",
        "nested": {
            "payload": {"card": RAW_SECRET},
            "local_variables": {
                "token": "secret-token",
                "request": {"body": RAW_SECRET},
            },
            "safe_child": {
                "error_class": "RuntimeError",
                "raw_payload": RAW_SECRET,
            },
        },
        "arbitrary_note": RAW_SECRET,
    }

    sanitized = sanitize_exception_context(context)
    serialized = json.dumps(sanitized)

    assert sanitized["task_id"] == "task-123"
    assert sanitized["component"] == "executor"
    assert sanitized["nested"]["payload"] == "[redacted]"
    assert sanitized["nested"]["local_variables"] == "[redacted]"
    assert sanitized["nested"]["safe_child"]["error_class"] == "RuntimeError"
    assert RAW_SECRET not in serialized
    assert "arbitrary_note" not in sanitized


def test_exception_event_keeps_dashboard_lookup_fields_without_task_payload():
    event = build_exception_event(
        RuntimeError("boom"),
        task={
            "id": "task-456",
            "target_agent": "agent-a",
            "payload": {"secret": RAW_SECRET},
        },
        context={"execution_id": "exec-789", "locals": {"payload": RAW_SECRET}},
    )

    serialized = json.dumps(event)

    assert event["task_id"] == "task-456"
    assert event["agent_id"] == "agent-a"
    assert event["error_class"] == "RuntimeError"
    assert event["context"]["execution_id"] == "exec-789"
    assert RAW_SECRET not in serialized
    assert "payload" not in event


def test_agent_executor_stores_sanitized_exception_result():
    async def failing_handler(agent_id, task):
        raise ValueError(f"failed task {task['id']}")

    async def run():
        executor = AgentExecutor()
        execution_id = await executor.execute(
            "agent-a",
            {"id": "task-789", "payload": {"card": RAW_SECRET}},
            failing_handler,
        )
        return executor.get_result(execution_id)

    result = asyncio.run(run())
    serialized = json.dumps(result)

    assert result["error"] == "ValueError"
    assert result["exception"]["task_id"] == "task-789"
    assert result["exception"]["agent_id"] == "agent-a"
    assert RAW_SECRET not in serialized
    assert "payload" not in serialized


def test_structured_formatter_writes_sanitized_exception_context():
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Task %s failed",
        args=("task-123",),
        exc_info=None,
    )
    record.exception_context = {
        "task_id": "task-123",
        "error_class": "RuntimeError",
        "payload": {"card": RAW_SECRET},
    }

    output = json.loads(formatter.format(record))

    assert output["message"] == "Task task-123 failed"
    assert output["exception"]["task_id"] == "task-123"
    assert output["exception"]["error_class"] == "RuntimeError"
    assert output["exception"]["payload"] == "[redacted]"
    assert RAW_SECRET not in json.dumps(output)


def test_orchestration_error_hook_receives_sanitized_task_and_event():
    events = []

    async def on_error(task, exception_event):
        events.append((task, exception_event))

    async def run():
        engine = OrchestrationEngine()
        engine.register_hook("on_error", on_error)
        await engine._execute_task(
            {
                "id": "task-321",
                "target_agent": "missing-agent",
                "payload": {"card": RAW_SECRET},
            }
        )

    asyncio.run(run())

    task, exception_event = events[0]
    serialized = json.dumps({"task": task, "exception": exception_event})

    assert task == {"id": "task-321", "target_agent": "missing-agent"}
    assert exception_event["task_id"] == "task-321"
    assert exception_event["agent_id"] == "missing-agent"
    assert exception_event["error_class"] == "ValueError"
    assert RAW_SECRET not in serialized
    assert "payload" not in serialized
