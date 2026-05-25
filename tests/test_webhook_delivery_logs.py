import json

from src.integrations.webhooks import (
    DeliveryStatus,
    REDACTED,
    WebhookDeliveryLog,
    WebhookEndpoint,
    build_delivery_log_context,
    redact_url,
)


def assert_no_secret(value, *secrets):
    encoded = json.dumps(value, sort_keys=True)
    for secret in secrets:
        assert secret not in encoded


def endpoint(workspace_id="workspace-a"):
    return WebhookEndpoint(
        endpoint_id="endpoint-1",
        workspace_id=workspace_id,
        url="https://hooks.example.test/run?token=url-token&safe=yes",
        secret="endpoint-secret",
    )


def test_valid_delivery_redacts_payload_headers_url_and_failure():
    log = WebhookDeliveryLog()
    log.register_endpoint(endpoint())

    record = log.deliver(
        delivery_id="delivery-1",
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        payload={"event": "run.failed", "webhook_secret": "payload-secret"},
        headers={"Authorization": "Bearer header-token"},
        failure=RuntimeError("request failed token=exception-token"),
    )

    assert record.status is DeliveryStatus.RETRY_SCHEDULED
    assert record.log_context["payload"]["webhook_secret"] == REDACTED
    assert record.log_context["headers"]["Authorization"] == REDACTED
    assert "token=" + REDACTED in record.log_context["failure"]["message"]
    assert "token=%5BREDACTED%5D" in record.log_context["endpoint_url"]
    assert_no_secret(
        record.log_context,
        "payload-secret",
        "header-token",
        "exception-token",
        "url-token",
        "endpoint-secret",
    )


def test_rejected_delivery_for_wrong_workspace_is_redacted():
    log = WebhookDeliveryLog()
    log.register_endpoint(endpoint(workspace_id="workspace-a"))

    record = log.deliver(
        delivery_id="delivery-2",
        workspace_id="workspace-b",
        endpoint_id="endpoint-1",
        payload={"token": "cross-workspace-token"},
        headers={"X-Signature": "signature-secret"},
    )

    assert record.status is DeliveryStatus.REJECTED
    assert record.payload["token"] == REDACTED
    assert record.log_context["headers"]["X-Signature"] == REDACTED
    assert_no_secret(
        record.log_context, "cross-workspace-token", "signature-secret"
    )


def test_delivery_records_are_idempotent_for_retries():
    log = WebhookDeliveryLog()
    log.register_endpoint(endpoint())

    first = log.deliver(
        delivery_id="delivery-3",
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        payload={"event": "run.completed"},
    )
    retry = log.deliver(
        delivery_id="delivery-3",
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        payload={"event": "run.completed", "api_key": "retry-secret"},
    )

    assert retry is first
    assert retry.status is DeliveryStatus.DELIVERED
    assert retry.attempt == 1
    assert_no_secret(retry.log_context, "retry-secret")


def test_rotated_or_disabled_endpoint_is_rejected_without_secret_leak():
    log = WebhookDeliveryLog()
    disabled = endpoint()
    disabled.enabled = False
    log.register_endpoint(disabled)

    record = log.deliver(
        delivery_id="delivery-4",
        workspace_id="workspace-a",
        endpoint_id="endpoint-1",
        payload={"client_secret": "disabled-secret"},
    )

    assert record.status is DeliveryStatus.REJECTED
    assert record.payload["client_secret"] == REDACTED
    assert_no_secret(record.log_context, "disabled-secret")


def test_helper_context_uses_secret_fingerprint_not_secret():
    context = build_delivery_log_context(
        endpoint=endpoint(),
        payload={"safe": True},
        headers={},
        failure=None,
    )

    assert context["secret_fingerprint"]
    assert context["secret_fingerprint"] != "endpoint-secret"
    assert_no_secret(context, "endpoint-secret")


def test_redact_url_only_masks_sensitive_query_values():
    assert redact_url(
        "https://hooks.example.test/a?token=abc&workspace=public"
    ) == "https://hooks.example.test/a?token=%5BREDACTED%5D&workspace=public"
