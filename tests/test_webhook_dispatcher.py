import pytest

from src.orchestrator.webhooks import (
    WebhookDispatcher,
    sanitize_webhook_payload,
)


@pytest.mark.asyncio
async def test_valid_delivery_sanitizes_internal_metadata():
    delivered = []
    dispatcher = WebhookDispatcher()
    endpoint = dispatcher.register_endpoint("workspace-a", delivered.append)

    record = await dispatcher.dispatch(
        endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-1",
        payload={
            "event": "task.completed",
            "task_id": "task-1",
            "internal_run_id": "run-secret",
            "nested": {"visible": True, "_trace": "hidden"},
        },
    )

    assert record.status == "delivered"
    assert delivered == [
        {
            "event": "task.completed",
            "task_id": "task-1",
            "nested": {"visible": True},
        }
    ]


@pytest.mark.asyncio
async def test_rate_limit_rejects_before_callback():
    now = [100.0]
    delivered = []
    dispatcher = WebhookDispatcher(clock=lambda: now[0])
    endpoint = dispatcher.register_endpoint(
        "workspace-a",
        delivered.append,
        max_deliveries=1,
        window_seconds=10.0,
    )

    first = await dispatcher.dispatch(
        endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-1",
        payload={"event": "task.completed"},
    )
    second = await dispatcher.dispatch(
        endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-2",
        payload={"event": "task.completed"},
    )

    assert first.status == "delivered"
    assert second.status == "rejected"
    assert second.reason == "rate_limited"
    assert second.retry_after == 10.0
    assert delivered == [{"event": "task.completed"}]


@pytest.mark.asyncio
async def test_retry_is_idempotent_per_endpoint_event():
    delivered = []
    dispatcher = WebhookDispatcher()
    endpoint = dispatcher.register_endpoint("workspace-a", delivered.append)

    first = await dispatcher.dispatch(
        endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-1",
        payload={"event": "task.completed"},
    )
    retry = await dispatcher.dispatch(
        endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-1",
        payload={"event": "task.completed"},
    )

    assert retry is first
    assert retry.duplicate is True
    assert delivered == [{"event": "task.completed"}]


@pytest.mark.asyncio
async def test_workspace_isolation_blocks_cross_workspace_delivery():
    delivered = []
    dispatcher = WebhookDispatcher()
    endpoint = dispatcher.register_endpoint("workspace-a", delivered.append)

    record = await dispatcher.dispatch(
        endpoint.endpoint_id,
        workspace_id="workspace-b",
        event_id="evt-1",
        payload={"event": "task.completed"},
    )

    assert record.status == "rejected"
    assert record.reason == "workspace_mismatch"
    assert delivered == []


@pytest.mark.asyncio
async def test_disabled_and_rotated_endpoints():
    delivered = []
    dispatcher = WebhookDispatcher()
    old_endpoint = dispatcher.register_endpoint(
        "workspace-a", delivered.append
    )
    new_endpoint = dispatcher.rotate_endpoint(old_endpoint.endpoint_id)

    old_record = await dispatcher.dispatch(
        old_endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-old",
        payload={"event": "task.completed"},
    )
    new_record = await dispatcher.dispatch(
        new_endpoint.endpoint_id,
        workspace_id="workspace-a",
        event_id="evt-new",
        payload={"event": "task.completed"},
    )

    assert old_record.status == "rejected"
    assert old_record.reason == "endpoint_disabled"
    assert new_record.status == "delivered"
    assert delivered == [{"event": "task.completed"}]


def test_sanitize_webhook_payload_removes_internal_fields_recursively():
    payload = sanitize_webhook_payload(
        {
            "public": True,
            "_private": "hidden",
            "run_metadata": {"queue": "secret"},
            "items": [{"internal_state": "hidden", "name": "ok"}],
        }
    )

    assert payload == {"public": True, "items": [{"name": "ok"}]}
