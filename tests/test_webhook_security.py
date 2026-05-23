import json

import pytest

from src.common.metrics import MetricsCollector
from src.webhook.security import WebhookSecurityError, WebhookSecurityGateway


def signed_headers(
    gateway,
    endpoint,
    payload,
    timestamp,
    secret=None,
    delivery_id="delivery-1",
):
    signature = gateway.sign_payload(
        secret or endpoint.secret, payload, timestamp)
    return {
        "x-ao-timestamp": str(timestamp),
        "x-ao-signature": signature,
        "x-ao-delivery-id": delivery_id,
    }


class TestWebhookSecurityGateway:
    def setup_method(self):
        self.metrics = MetricsCollector()
        self.gateway = WebhookSecurityGateway(metrics=self.metrics)
        self.endpoint = self.gateway.register_endpoint(
            workspace_id="workspace-a",
            url="https://example.com/webhook",
            secret="secret-a",
            replay_window_seconds=60,
            endpoint_id="endpoint-a",
        )

    def payload(self, **extra):
        value = {"event": "run.completed", "result": "ok",
                 "run_metadata": {"host": "worker-1"}}
        value.update(extra)
        return json.dumps(value).encode("utf-8")

    def test_valid_delivery_sanitizes_callback(self):
        raw_payload = self.payload(_internal_trace="secret")
        headers = signed_headers(
            self.gateway, self.endpoint, raw_payload, timestamp=1000)

        record = self.gateway.deliver_event(
            "endpoint-a",
            "workspace-a",
            raw_payload,
            headers,
            event_id="event-1",
            now=1005,
        )

        assert record.status == "accepted"
        assert record.callback_payload == {
            "event": "run.completed", "result": "ok"}
        assert self.gateway.audit_log[-1] == {
            "endpoint_id": "endpoint-a",
            "workspace_id": "workspace-a",
            "decision": "accepted",
            "reason": "verified",
        }
        assert self.metrics.snapshot(
        )["counters"]["webhook.delivery.accepted"] == 1

    def test_rejects_stale_signature_without_persisting_delivery(self):
        raw_payload = self.payload()
        headers = signed_headers(
            self.gateway, self.endpoint, raw_payload, timestamp=900)

        with pytest.raises(
            WebhookSecurityError,
            match="replay_window_expired",
        ):
            self.gateway.deliver_event(
                "endpoint-a",
                "workspace-a",
                raw_payload,
                headers,
                event_id="event-1",
                now=1000,
            )

        assert self.gateway.delivery_records == []
        assert self.gateway.audit_log[-1]["reason"] == "replay_window_expired"
        assert self.metrics.snapshot(
        )["counters"]["webhook.delivery.rejected"] == 1

    def test_retries_are_idempotent_for_same_delivery_id(self):
        raw_payload = self.payload()
        headers = signed_headers(
            self.gateway, self.endpoint, raw_payload, timestamp=1000)

        first = self.gateway.deliver_event(
            "endpoint-a",
            "workspace-a",
            raw_payload,
            headers,
            event_id="event-1",
            now=1000,
        )
        retry = self.gateway.deliver_event(
            "endpoint-a",
            "workspace-a",
            raw_payload,
            headers,
            event_id="event-1",
            now=1001,
        )

        assert retry is first
        assert retry.attempts == 2
        assert len(self.gateway.delivery_records) == 1
        assert self.gateway.audit_log[-1]["reason"] == "idempotent_retry"

    def test_rejects_cross_workspace_delivery_before_parsing_payload(self):
        raw_payload = b"{not-json"
        headers = signed_headers(
            self.gateway, self.endpoint, raw_payload, timestamp=1000)

        with pytest.raises(WebhookSecurityError, match="workspace_mismatch"):
            self.gateway.deliver_event(
                "endpoint-a",
                "workspace-b",
                raw_payload,
                headers,
                event_id="event-1",
                now=1000,
            )

        assert self.gateway.delivery_records == []
        assert self.gateway.audit_log[-1]["reason"] == "workspace_mismatch"

    def test_disabled_endpoint_and_rotated_secret_paths_are_enforced(self):
        raw_payload = self.payload()
        self.gateway.rotate_secret("endpoint-a", "secret-b")
        old_headers = signed_headers(
            self.gateway,
            self.endpoint,
            raw_payload,
            timestamp=1000,
            secret="secret-a",
            delivery_id="delivery-old",
        )
        old_secret_record = self.gateway.deliver_event(
            "endpoint-a",
            "workspace-a",
            raw_payload,
            old_headers,
            event_id="event-old",
            now=1000,
        )
        assert old_secret_record.status == "accepted"

        self.gateway.disable_endpoint("endpoint-a")
        new_headers = signed_headers(
            self.gateway,
            self.endpoint,
            raw_payload,
            timestamp=1010,
            secret="secret-b",
            delivery_id="delivery-disabled",
        )
        with pytest.raises(WebhookSecurityError, match="endpoint_disabled"):
            self.gateway.deliver_event(
                "endpoint-a",
                "workspace-a",
                raw_payload,
                new_headers,
                event_id="event-disabled",
                now=1010,
            )
