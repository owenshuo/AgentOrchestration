"""Webhook signature verification and idempotent delivery records."""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from uuid import uuid4

from src.common.metrics import MetricsCollector, metrics as default_metrics


class WebhookSecurityError(ValueError):
    """Raised when a webhook endpoint cannot be trusted for delivery."""


@dataclass
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    secret: str
    enabled: bool = True
    replay_window_seconds: int = 300
    rotated_secrets: Tuple[str, ...] = field(default_factory=tuple)


@dataclass
class DeliveryRecord:
    id: str
    endpoint_id: str
    workspace_id: str
    event_id: str
    status: str
    callback_payload: Dict[str, Any]
    attempts: int = 1
    rejected_reason: Optional[str] = None


class WebhookSecurityGateway:
    """Verify endpoint trust before payload parsing or delivery recording."""

    TIMESTAMP_HEADER = "x-ao-timestamp"
    SIGNATURE_HEADER = "x-ao-signature"
    DELIVERY_ID_HEADER = "x-ao-delivery-id"
    INTERNAL_FIELDS = {
        "internal_metadata",
        "operator_notes",
        "run_metadata",
        "scheduler_state",
        "trace",
    }

    def __init__(self, metrics: Optional[MetricsCollector] = None):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[str, DeliveryRecord] = {}
        self._seen_signatures: Set[Tuple[str, str, int]] = set()
        self._audit: List[Dict[str, Any]] = []
        self._metrics = metrics or default_metrics

    @property
    def audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit)

    @property
    def delivery_records(self) -> List[DeliveryRecord]:
        return list(self._deliveries.values())

    def register_endpoint(
        self,
        workspace_id: str,
        url: str,
        secret: str,
        replay_window_seconds: int = 300,
        endpoint_id: Optional[str] = None,
    ) -> WebhookEndpoint:
        if replay_window_seconds <= 0:
            raise ValueError("replay_window_seconds must be positive")
        if not secret:
            raise ValueError("secret is required")

        endpoint = WebhookEndpoint(
            id=endpoint_id or str(uuid4()),
            workspace_id=workspace_id,
            url=url,
            secret=secret,
            replay_window_seconds=replay_window_seconds,
        )
        self._endpoints[endpoint.id] = endpoint
        return endpoint

    def disable_endpoint(self, endpoint_id: str) -> None:
        self._get_endpoint(endpoint_id).enabled = False

    def rotate_secret(self, endpoint_id: str, new_secret: str) -> None:
        if not new_secret:
            raise ValueError("new_secret is required")
        endpoint = self._get_endpoint(endpoint_id)
        endpoint.rotated_secrets = (
            endpoint.secret,) + endpoint.rotated_secrets
        endpoint.secret = new_secret

    def sign_payload(self, secret: str, payload: bytes, timestamp: int) -> str:
        signed = f"{timestamp}.".encode("utf-8") + payload
        return hmac.new(
            secret.encode("utf-8"),
            signed,
            hashlib.sha256,
        ).hexdigest()

    def deliver_event(
        self,
        endpoint_id: str,
        workspace_id: str,
        raw_payload: bytes,
        headers: Dict[str, str],
        event_id: str,
        now: Optional[float] = None,
    ) -> DeliveryRecord:
        endpoint = self._get_endpoint(endpoint_id)
        delivery_id = headers.get(
            self.DELIVERY_ID_HEADER) or f"{endpoint_id}:{event_id}"
        existing = self._deliveries.get(delivery_id)
        if existing:
            existing.attempts += 1
            self._record_audit(endpoint, "accepted", "idempotent_retry")
            self._metrics.increment("webhook.delivery.retry")
            return existing

        try:
            self._verify_trust(
                endpoint,
                workspace_id,
                raw_payload,
                headers,
                now,
            )
            parsed_payload = json.loads(raw_payload.decode("utf-8"))
            if not isinstance(parsed_payload, dict):
                raise WebhookSecurityError("payload must be a JSON object")
        except Exception as exc:
            reason = self._safe_reason(exc)
            self._record_audit(endpoint, "rejected", reason)
            self._metrics.increment("webhook.delivery.rejected")
            raise WebhookSecurityError(reason) from exc

        callback_payload = self._public_payload(parsed_payload)
        record = DeliveryRecord(
            id=delivery_id,
            endpoint_id=endpoint.id,
            workspace_id=workspace_id,
            event_id=event_id,
            status="accepted",
            callback_payload=callback_payload,
        )
        self._deliveries[delivery_id] = record
        self._record_audit(endpoint, "accepted", "verified")
        self._metrics.increment("webhook.delivery.accepted")
        return record

    def _verify_trust(
        self,
        endpoint: WebhookEndpoint,
        workspace_id: str,
        raw_payload: bytes,
        headers: Dict[str, str],
        now: Optional[float],
    ) -> None:
        if not endpoint.enabled:
            raise WebhookSecurityError("endpoint_disabled")
        if endpoint.workspace_id != workspace_id:
            raise WebhookSecurityError("workspace_mismatch")

        timestamp = self._parse_timestamp(headers.get(self.TIMESTAMP_HEADER))
        current_time = int(now if now is not None else time.time())
        if abs(current_time - timestamp) > endpoint.replay_window_seconds:
            raise WebhookSecurityError("replay_window_expired")

        signature = headers.get(self.SIGNATURE_HEADER, "")
        if not self._signature_matches(
            endpoint,
            raw_payload,
            timestamp,
            signature,
        ):
            raise WebhookSecurityError("invalid_signature")

        replay_key = (endpoint.id, signature, timestamp)
        if replay_key in self._seen_signatures:
            raise WebhookSecurityError("signature_replay")
        self._seen_signatures.add(replay_key)

    def _signature_matches(
        self,
        endpoint: WebhookEndpoint,
        raw_payload: bytes,
        timestamp: int,
        signature: str,
    ) -> bool:
        secrets: Iterable[str] = (endpoint.secret, *endpoint.rotated_secrets)
        return any(
            hmac.compare_digest(self.sign_payload(
                secret, raw_payload, timestamp), signature)
            for secret in secrets
        )

    def _parse_timestamp(self, value: Optional[str]) -> int:
        if value is None:
            raise WebhookSecurityError("missing_timestamp")
        try:
            return int(value)
        except ValueError as exc:
            raise WebhookSecurityError("invalid_timestamp") from exc

    def _public_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if key not in self.INTERNAL_FIELDS and not key.startswith("_")
        }

    def _record_audit(
        self,
        endpoint: WebhookEndpoint,
        decision: str,
        reason: str,
    ) -> None:
        self._audit.append(
            {
                "endpoint_id": endpoint.id,
                "workspace_id": endpoint.workspace_id,
                "decision": decision,
                "reason": reason,
            }
        )

    def _safe_reason(self, exc: Exception) -> str:
        if isinstance(exc, WebhookSecurityError):
            return str(exc)
        return exc.__class__.__name__

    def _get_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        try:
            return self._endpoints[endpoint_id]
        except KeyError as exc:
            raise WebhookSecurityError("unknown_endpoint") from exc
