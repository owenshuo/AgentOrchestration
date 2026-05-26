import pytest
from fastapi import HTTPException

from src.api.webhooks import (
    WebhookDeliveryCreate,
    WebhookStore,
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
)


def test_subscription_create_rejects_unknown_event_before_persistence():
    store = WebhookStore()

    with pytest.raises(HTTPException) as excinfo:
        store.create(
            WebhookSubscriptionCreate(
                workspace_id="workspace-a",
                endpoint_url="https://hooks.example.test/agent",
                event_types=["task.completed", "billing.exported"],
            )
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["invalid"] == ["billing.exported"]
    assert store._subscriptions == {}


def test_subscription_create_deduplicates_allowed_events():
    store = WebhookStore()

    subscription = store.create(
        WebhookSubscriptionCreate(
            workspace_id="workspace-a",
            endpoint_url="https://hooks.example.test/agent",
            event_types=["task.completed", "task.completed"],
        )
    )

    assert subscription.event_types == ("task.completed",)


def test_delivery_is_idempotent_scoped_and_sanitized():
    store = WebhookStore()
    subscription = store.create(
        WebhookSubscriptionCreate(
            workspace_id="workspace-a",
            endpoint_url="https://hooks.example.test/agent",
            event_types=["task.completed"],
        )
    )

    first = store.deliver(
        subscription.id,
        WebhookDeliveryCreate(
            workspace_id="workspace-a",
            event_type="task.completed",
            delivery_id="delivery-1",
            payload={
                "task_id": "task-1",
                "internal_trace_id": "trace",
                "_debug": True,
                "secret": "hidden",
            },
        ),
    )
    duplicate = store.deliver(
        subscription.id,
        WebhookDeliveryCreate(
            workspace_id="workspace-a",
            event_type="task.completed",
            delivery_id="delivery-1",
            payload={"task_id": "changed"},
        ),
    )

    assert first is duplicate
    assert first.status == "queued"
    assert first.payload == {"task_id": "task-1"}
    assert "secret" not in first.public_view()


def test_wrong_workspace_and_unsubscribed_events_fail_closed():
    store = WebhookStore()
    subscription = store.create(
        WebhookSubscriptionCreate(
            workspace_id="workspace-a",
            endpoint_url="https://hooks.example.test/agent",
            event_types=["task.completed"],
        )
    )

    wrong_workspace = store.deliver(
        subscription.id,
        WebhookDeliveryCreate(
            workspace_id="workspace-b",
            event_type="task.completed",
            delivery_id="delivery-1",
        ),
    )
    wrong_event = store.deliver(
        subscription.id,
        WebhookDeliveryCreate(
            workspace_id="workspace-a",
            event_type="task.failed",
            delivery_id="delivery-2",
        ),
    )

    assert wrong_workspace.status == "rejected"
    assert wrong_workspace.error_code == "subscription_scope_mismatch"
    assert wrong_event.status == "rejected"
    assert wrong_event.error_code == "event_not_subscribed"


def test_disabled_and_rotated_endpoint_delivery_are_bounded():
    store = WebhookStore()
    subscription = store.create(
        WebhookSubscriptionCreate(
            workspace_id="workspace-a",
            endpoint_url="https://hooks.example.test/agent",
            event_types=["task.completed"],
        )
    )

    store.update(
        subscription.id,
        WebhookSubscriptionUpdate(
            workspace_id="workspace-a",
            endpoint_url="https://hooks-v2.example.test/agent",
        ),
    )
    assert subscription.endpoint_version == 2

    delivery = store.deliver(
        subscription.id,
        WebhookDeliveryCreate(
            workspace_id="workspace-a",
            event_type="task.completed",
            delivery_id="delivery-1",
            payload={"task_id": "task-1"},
        ),
    )
    store.update(
        subscription.id,
        WebhookSubscriptionUpdate(workspace_id="workspace-a", disabled=True),
    )
    disabled = store.deliver(
        subscription.id,
        WebhookDeliveryCreate(
            workspace_id="workspace-a",
            event_type="task.completed",
            delivery_id="delivery-2",
        ),
    )

    assert delivery.endpoint_version == 2
    assert disabled.status == "rejected"
    assert disabled.error_code == "subscription_disabled"
