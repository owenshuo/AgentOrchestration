from src.api.delivery import DeliveryControlError, WebhookFanoutController


def test_fanout_accepts_valid_delivery_without_internal_fields():
    controller = WebhookFanoutController(clock=lambda: 10.0)
    endpoint = controller.register_endpoint(
        "workspace-a",
        "https://example.com/hook",
        endpoint_id="endpoint-a",
    )

    record = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-1",
        {"secret": "payload"},
        secret_version=1,
    )

    assert record["status"] == "accepted"
    assert "payload" not in record
    assert "url" not in record
    assert "secret_version" not in record


def test_rate_limit_is_enforced_per_endpoint_before_expensive_work():
    now = {"value": 10.0}
    controller = WebhookFanoutController(clock=lambda: now["value"])
    endpoint = controller.register_endpoint(
        "workspace-a",
        "https://example.com/hook",
        endpoint_id="endpoint-a",
        rate_limit=1,
        window_seconds=60.0,
    )

    first = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-1",
        {"event": "first"},
    )
    now["value"] = 12.0
    second = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-2",
        {"event": "second"},
    )

    assert first["status"] == "accepted"
    assert second["status"] == "backpressure"
    assert second["error_code"] == "rate_limited"
    assert second["retry_after"] == 58.0
    assert "payload" not in second


def test_idempotent_retry_replays_without_consuming_rate_limit():
    now = {"value": 10.0}
    controller = WebhookFanoutController(clock=lambda: now["value"])
    endpoint = controller.register_endpoint(
        "workspace-a",
        "https://example.com/hook",
        endpoint_id="endpoint-a",
        rate_limit=1,
        window_seconds=60.0,
    )

    first = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-1",
        {"event": "first"},
    )
    retry = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-1",
        {"event": "changed"},
    )

    assert retry == first
    assert controller.audit_report()[-1]["action"] == "replayed"


def test_rate_limit_is_scoped_by_endpoint_and_workspace():
    controller = WebhookFanoutController(clock=lambda: 10.0)
    first = controller.register_endpoint(
        "workspace-a",
        "https://example.com/a",
        endpoint_id="endpoint-a",
        rate_limit=1,
    )
    second = controller.register_endpoint(
        "workspace-b",
        "https://example.com/b",
        endpoint_id="endpoint-b",
        rate_limit=1,
    )

    accepted_a = controller.fanout(
        "workspace-a",
        first.id,
        "event-a",
        {},
    )
    accepted_b = controller.fanout(
        "workspace-b",
        second.id,
        "event-b",
        {},
    )

    assert accepted_a["status"] == "accepted"
    assert accepted_b["status"] == "accepted"


def test_workspace_mismatch_disabled_and_rotated_endpoint_fail_closed():
    controller = WebhookFanoutController(clock=lambda: 10.0)
    endpoint = controller.register_endpoint(
        "workspace-a",
        "https://example.com/hook",
        endpoint_id="endpoint-a",
    )

    mismatch = controller.fanout("workspace-b", endpoint.id, "event-1", {})
    controller.disable_endpoint("workspace-a", endpoint.id)
    disabled = controller.fanout("workspace-a", endpoint.id, "event-2", {})
    controller = WebhookFanoutController(clock=lambda: 10.0)
    endpoint = controller.register_endpoint(
        "workspace-a",
        "https://example.com/hook",
        endpoint_id="endpoint-a",
    )
    controller.rotate_secret("workspace-a", endpoint.id)
    rotated = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-3",
        {},
        secret_version=1,
    )

    assert mismatch["error_code"] == "endpoint_scope_mismatch"
    assert disabled["error_code"] == "endpoint_disabled"
    assert rotated["error_code"] == "endpoint_secret_rotated"


def test_callback_payload_and_audit_do_not_expose_private_fields():
    controller = WebhookFanoutController(clock=lambda: 10.0)
    endpoint = controller.register_endpoint(
        "workspace-a",
        "https://example.com/hook",
        endpoint_id="endpoint-a",
    )
    record = controller.fanout(
        "workspace-a",
        endpoint.id,
        "event-1",
        {"token": "private"},
    )

    callback = controller.callback_payload(record["id"])
    audit_text = str(controller.audit_report())

    assert callback == record
    assert "private" not in str(callback)
    assert "token" not in str(callback)
    assert "https://example.com" not in audit_text


def test_rejects_invalid_endpoint_configuration():
    controller = WebhookFanoutController()

    try:
        controller.register_endpoint("workspace-a", "http://example.com/hook")
    except DeliveryControlError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("expected invalid endpoint to fail")
