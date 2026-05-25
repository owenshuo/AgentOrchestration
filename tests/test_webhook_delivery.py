import pytest

from src.webhooks import (
    EndpointState,
    WebhookDeliveryService,
    WebhookDeliveryStateError,
)


def event_payload(**overrides):
    payload = {
        "event_id": "event-1",
        "workspace_id": "workspace-a",
        "endpoint_generation": 1,
        "type": "task.completed",
        "data": {"task_id": "task-1"},
        "internal_trace": "trace-123",
        "internal_retry_state": {"worker": "worker-a"},
        "secret": "do-not-send",
    }
    payload.update(overrides)
    return payload


def service_with_endpoint(state=EndpointState.ENABLED):
    service = WebhookDeliveryService()
    service.register_endpoint(
        "endpoint-a",
        "workspace-a",
        "https://example.test/webhook",
        state=state,
    )
    return service


def test_valid_delivery_is_idempotent_and_sanitizes_callback_payload():
    service = service_with_endpoint()
    event = event_payload()

    first = service.deliver(event, "endpoint-a", "workspace-a")
    second = service.deliver(event, "endpoint-a", "workspace-a")

    assert first is second
    assert first.status == "delivered"
    assert first.callback_payload == {
        "event_id": "event-1",
        "workspace_id": "workspace-a",
        "type": "task.completed",
        "data": {"task_id": "task-1"},
    }


def test_disabled_endpoint_is_rejected_before_delivery_record():
    service = service_with_endpoint(state=EndpointState.DISABLED)

    with pytest.raises(WebhookDeliveryStateError, match="disabled"):
        service.deliver(event_payload(), "endpoint-a", "workspace-a")


def test_retry_revalidates_endpoint_state_and_permanently_fails():
    service = service_with_endpoint()
    service.deliver(event_payload(), "endpoint-a", "workspace-a", attempt=1)
    service.set_endpoint_state(
        "endpoint-a",
        "workspace-a",
        EndpointState.DISABLED,
    )

    retry = service.retry(event_payload(), "endpoint-a", "workspace-a", 2)

    assert retry.status == "permanently_failed"
    assert retry.callback_payload == {}
    assert service.audit_records == [
        {
            "event_id": "event-1",
            "endpoint_id": "endpoint-a",
            "workspace_id": "workspace-a",
            "decision": "retry_blocked",
            "reason": "endpoint is disabled",
        }
    ]


def test_workspace_isolation_blocks_cross_workspace_delivery():
    service = service_with_endpoint()

    with pytest.raises(WebhookDeliveryStateError, match="not found"):
        service.deliver(event_payload(), "endpoint-a", "workspace-b")

    with pytest.raises(WebhookDeliveryStateError, match="workspace isolation"):
        service.deliver(
            event_payload(workspace_id="workspace-b"),
            "endpoint-a",
            "workspace-a",
        )


def test_rotated_endpoint_generation_blocks_stale_queued_event():
    service = WebhookDeliveryService()
    service.register_endpoint(
        "endpoint-a",
        "workspace-a",
        "https://example.test/webhook",
        generation=2,
    )

    with pytest.raises(WebhookDeliveryStateError, match="generation"):
        service.deliver(
            event_payload(endpoint_generation=1),
            "endpoint-a",
            "workspace-a",
        )
