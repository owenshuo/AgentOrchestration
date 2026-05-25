"""Webhook delivery records with secret-safe failure logging."""

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import logging
from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "password",
    "secret",
    "signature",
    "token",
    "webhook_secret",
    "x-api-key",
    "x-signature",
}


class DeliveryStatus(Enum):
    DELIVERED = "delivered"
    REJECTED = "rejected"
    RETRY_SCHEDULED = "retry_scheduled"


@dataclass
class WebhookEndpoint:
    endpoint_id: str
    workspace_id: str
    url: str
    secret: str
    enabled: bool = True
    rotated_secrets: Set[str] = field(default_factory=set)


@dataclass
class DeliveryRecord:
    delivery_id: str
    endpoint_id: str
    workspace_id: str
    status: DeliveryStatus
    attempt: int
    payload: Dict[str, Any]
    log_context: Dict[str, Any]


class WebhookDeliveryLog:
    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[Tuple[str, str], DeliveryRecord] = {}

    def register_endpoint(self, endpoint: WebhookEndpoint) -> None:
        if not endpoint.enabled:
            self._endpoints.pop(endpoint.endpoint_id, None)
            return
        self._endpoints[endpoint.endpoint_id] = endpoint

    def deliver(
        self,
        *,
        delivery_id: str,
        workspace_id: str,
        endpoint_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
        failure: Optional[Exception] = None,
    ) -> DeliveryRecord:
        key = (workspace_id, delivery_id)
        if key in self._deliveries:
            return self._deliveries[key]

        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint or endpoint.workspace_id != workspace_id:
            record = self._record_rejection(
                delivery_id,
                workspace_id,
                endpoint_id,
                payload,
                headers,
                failure,
            )
            self._deliveries[key] = record
            return record

        status = DeliveryStatus.DELIVERED
        if failure is not None:
            status = DeliveryStatus.RETRY_SCHEDULED

        record = DeliveryRecord(
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            status=status,
            attempt=1,
            payload=redact_payload(payload),
            log_context=build_delivery_log_context(
                endpoint=endpoint,
                payload=payload,
                headers=headers or {},
                failure=failure,
            ),
        )
        self._deliveries[key] = record
        logger.info(
            "webhook delivery recorded",
            extra={"webhook": record.log_context},
        )
        return record

    def _record_rejection(
        self,
        delivery_id: str,
        workspace_id: str,
        endpoint_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, Any]],
        failure: Optional[Exception],
    ) -> DeliveryRecord:
        record = DeliveryRecord(
            delivery_id=delivery_id,
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            status=DeliveryStatus.REJECTED,
            attempt=1,
            payload=redact_payload(payload),
            log_context={
                "endpoint_id": endpoint_id,
                "workspace_id": workspace_id,
                "status": DeliveryStatus.REJECTED.value,
                "headers": redact_payload(headers or {}),
                "payload": redact_payload(payload),
                "failure": redact_failure(failure),
            },
        )
        logger.warning(
            "webhook delivery rejected",
            extra={"webhook": record.log_context},
        )
        return record


def build_delivery_log_context(
    *,
    endpoint: WebhookEndpoint,
    payload: Dict[str, Any],
    headers: Dict[str, Any],
    failure: Optional[Exception],
) -> Dict[str, Any]:
    return {
        "endpoint_id": endpoint.endpoint_id,
        "workspace_id": endpoint.workspace_id,
        "endpoint_url": redact_url(endpoint.url),
        "secret_fingerprint": secret_fingerprint(endpoint.secret),
        "status": (
            DeliveryStatus.RETRY_SCHEDULED.value
            if failure is not None
            else DeliveryStatus.DELIVERED.value
        ),
        "headers": redact_payload(headers),
        "payload": redact_payload(payload),
        "failure": redact_failure(failure),
    }


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            if is_sensitive_key(str(key)):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_payload(child)
        return redacted
    if isinstance(value, list):
        return [redact_payload(child) for child in value]
    return value


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, REDACTED if is_sensitive_key(key) else value))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), "")
    )


def redact_failure(failure: Optional[Exception]) -> Optional[Dict[str, str]]:
    if failure is None:
        return None
    return {
        "type": failure.__class__.__name__,
        "message": redact_text(str(failure)),
    }


def redact_text(value: str) -> str:
    redacted = value
    for marker in ("token=", "secret=", "password=", "signature=", "api_key="):
        if marker in redacted.lower():
            redacted = _redact_marker_value(redacted, marker)
    return redacted


def _redact_marker_value(value: str, marker: str) -> str:
    lower = value.lower()
    index = lower.find(marker)
    while index != -1:
        start = index + len(marker)
        end = start
        while end < len(value) and value[end] not in " &,;\n\t":
            end += 1
        value = value[:start] + REDACTED + value[end:]
        lower = value.lower()
        index = lower.find(marker, start + len(REDACTED))
    return value


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or any(
        token in normalized
        for token in ("secret", "token", "password", "signature")
    )


def secret_fingerprint(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()[:12]
