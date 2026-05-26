import pytest

from src.common.webhooks import (
    WebhookPrincipal,
    WebhookSecretStore,
    WebhookSecurityError,
)


def principal(**overrides):
    values = {
        "principal_id": "user-1",
        "workspace_id": "workspace-a",
        "roles": {"admin"},
        "active": True,
    }
    values.update(overrides)
    return WebhookPrincipal(**values)


def test_secret_rotation_requires_endpoint_workspace_owner_scope():
    store = WebhookSecretStore()
    endpoint = store.register_endpoint(
        principal(),
        "https://hooks.example.test/a",
        "old-secret",
    )

    with pytest.raises(WebhookSecurityError, match="another workspace"):
        store.rotate_secret(
            principal(workspace_id="workspace-b"),
            endpoint.endpoint_id,
            "new-secret",
        )

    rotated = store.rotate_secret(
        principal(),
        endpoint.endpoint_id,
        "new-secret",
    )

    assert rotated.secret_version == 2
    assert rotated._secret == ""


def test_delivery_rejects_stale_secret_after_rotation():
    store = WebhookSecretStore()
    endpoint = store.register_endpoint(
        principal(),
        "https://hooks.example.test/a",
        "old-secret",
    )
    store.rotate_secret(principal(), endpoint.endpoint_id, "new-secret")

    with pytest.raises(WebhookSecurityError, match="secret has rotated"):
        store.deliver(
            principal(),
            endpoint.endpoint_id,
            {"type": "task.completed", "internal": "do-not-return"},
            "delivery-1",
            secret_version=1,
        )


def test_delivery_is_workspace_scoped_and_idempotent():
    store = WebhookSecretStore()
    endpoint = store.register_endpoint(
        principal(),
        "https://hooks.example.test/a",
        "secret",
    )

    with pytest.raises(WebhookSecurityError, match="another workspace"):
        store.deliver(
            principal(workspace_id="workspace-b"),
            endpoint.endpoint_id,
            {"type": "task.completed"},
            "delivery-1",
        )

    first = store.deliver(
        principal(),
        endpoint.endpoint_id,
        {"type": "task.completed", "internal": "do-not-return"},
        "delivery-1",
        secret_version=1,
    )
    retry = store.deliver(
        principal(),
        endpoint.endpoint_id,
        {"type": "task.completed"},
        "delivery-1",
        secret_version=1,
    )

    assert retry == first
    assert first["workspace_id"] == "workspace-a"
    assert first["event_type"] == "task.completed"
    assert "internal" not in str(first)


def test_disabled_endpoint_rejects_delivery():
    store = WebhookSecretStore()
    endpoint = store.register_endpoint(
        principal(),
        "https://hooks.example.test/a",
        "secret",
    )
    store.disable_endpoint(principal(), endpoint.endpoint_id)

    with pytest.raises(WebhookSecurityError, match="disabled"):
        store.deliver(
            principal(),
            endpoint.endpoint_id,
            {"type": "task.completed"},
            "delivery-1",
        )


def test_audit_report_does_not_expose_secrets_or_event_payloads():
    store = WebhookSecretStore()
    endpoint = store.register_endpoint(
        principal(),
        "https://hooks.example.test/a",
        "secret-token",
    )
    store.rotate_secret(principal(), endpoint.endpoint_id, "new-secret-token")
    store.deliver(
        principal(),
        endpoint.endpoint_id,
        {"type": "task.completed", "token": "private"},
        "delivery-1",
        secret_version=2,
    )

    report = store.audit_report()

    assert report["total"] == 3
    assert report["by_operation"] == {
        "register": 1,
        "rotate_secret": 1,
        "deliver": 1,
    }
    assert report["by_decision"] == {"allow": 3}
    assert "secret-token" not in str(report)
    assert "new-secret-token" not in str(report)
    assert "private" not in str(report)

    report["recent"][0]["decision"] = "changed"
    assert store.audit_events[0]["decision"] == "allow"
