"""Webhook endpoint dispatch controls."""

import inspect
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


INTERNAL_PAYLOAD_FIELDS = {
    "internal_run_id",
    "run_metadata",
    "scheduler_state",
    "queue_slot",
    "worker_pid",
    "retry_token",
}


@dataclass
class WebhookEndpoint:
    """Registered webhook endpoint with endpoint-scoped dispatch controls."""

    workspace_id: str
    callback: Callable[[Dict[str, Any]], Any]
    endpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    enabled: bool = True
    max_deliveries: int = 60
    window_seconds: float = 60.0
    version: int = 1


@dataclass
class DeliveryRecord:
    """Stable delivery result for a single endpoint/event pair."""

    endpoint_id: str
    workspace_id: str
    event_id: str
    status: str
    attempts: int
    reason: Optional[str] = None
    retry_after: Optional[float] = None
    duplicate: bool = False


class WebhookDispatcher:
    """Dispatches webhook events while enforcing endpoint-level safeguards."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._rate_windows: Dict[str, List[float]] = {}
        self._deliveries: Dict[Tuple[str, str], DeliveryRecord] = {}

    def register_endpoint(
        self,
        workspace_id: str,
        callback: Callable[[Dict[str, Any]], Any],
        *,
        endpoint_id: Optional[str] = None,
        max_deliveries: int = 60,
        window_seconds: float = 60.0,
    ) -> WebhookEndpoint:
        if max_deliveries < 1:
            raise ValueError("max_deliveries must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id or str(uuid.uuid4()),
            workspace_id=workspace_id,
            callback=callback,
            max_deliveries=max_deliveries,
            window_seconds=window_seconds,
        )
        self._endpoints[endpoint.endpoint_id] = endpoint
        self._rate_windows.setdefault(endpoint.endpoint_id, [])
        return endpoint

    def disable_endpoint(self, endpoint_id: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            return False
        endpoint.enabled = False
        return True

    def rotate_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = self._require_endpoint(endpoint_id)
        endpoint.enabled = False
        return self.register_endpoint(
            endpoint.workspace_id,
            endpoint.callback,
            max_deliveries=endpoint.max_deliveries,
            window_seconds=endpoint.window_seconds,
        )

    async def dispatch(
        self,
        endpoint_id: str,
        *,
        workspace_id: str,
        event_id: str,
        payload: Mapping[str, Any],
    ) -> DeliveryRecord:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            return self._record(
                endpoint_id, workspace_id, event_id, "rejected",
                "unknown_endpoint",
            )

        existing = self._deliveries.get((endpoint_id, event_id))
        if existing is not None:
            existing.duplicate = True
            return existing

        if endpoint.workspace_id != workspace_id:
            return self._record(
                endpoint_id, workspace_id, event_id, "rejected",
                "workspace_mismatch",
            )

        if not endpoint.enabled:
            return self._record(
                endpoint_id, workspace_id, event_id, "rejected",
                "endpoint_disabled",
            )

        retry_after = self._check_rate_limit(endpoint)
        if retry_after is not None:
            return self._record(
                endpoint_id,
                workspace_id,
                event_id,
                "rejected",
                "rate_limited",
                retry_after=retry_after,
            )

        sanitized = sanitize_webhook_payload(payload)
        result = endpoint.callback(sanitized)
        if inspect.isawaitable(result):
            await result

        return self._record(endpoint_id, workspace_id, event_id, "delivered")

    async def fanout(
        self,
        *,
        workspace_id: str,
        event_id: str,
        payload: Mapping[str, Any],
    ) -> List[DeliveryRecord]:
        records: List[DeliveryRecord] = []
        for endpoint in list(self._endpoints.values()):
            if endpoint.workspace_id != workspace_id:
                continue
            record = await self.dispatch(
                endpoint.endpoint_id,
                workspace_id=workspace_id,
                event_id=event_id,
                payload=payload,
            )
            records.append(record)
        return records

    def _check_rate_limit(self, endpoint: WebhookEndpoint) -> Optional[float]:
        now = self._clock()
        window = self._rate_windows.setdefault(endpoint.endpoint_id, [])
        window[:] = [t for t in window if now - t < endpoint.window_seconds]

        if len(window) >= endpoint.max_deliveries:
            oldest = min(window)
            return max(endpoint.window_seconds - (now - oldest), 0.0)

        window.append(now)
        return None

    def _record(
        self,
        endpoint_id: str,
        workspace_id: str,
        event_id: str,
        status: str,
        reason: Optional[str] = None,
        *,
        retry_after: Optional[float] = None,
    ) -> DeliveryRecord:
        record = DeliveryRecord(
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            event_id=event_id,
            status=status,
            reason=reason,
            retry_after=retry_after,
            attempts=1,
        )
        self._deliveries[(endpoint_id, event_id)] = record
        return record

    def _require_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise KeyError(f"Webhook endpoint {endpoint_id} not found")
        return endpoint


def sanitize_webhook_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a public webhook payload without internal-only metadata."""

    sanitized: Dict[str, Any] = {}
    for key, value in payload.items():
        if (
            key.startswith("_")
            or key.startswith("internal_")
            or key in INTERNAL_PAYLOAD_FIELDS
        ):
            continue
        sanitized[key] = _sanitize_value(value)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return sanitize_webhook_payload(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    return value
