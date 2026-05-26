"""Webhook delivery fanout controls."""

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import uuid4


class DeliveryControlError(ValueError):
    """Raised when a webhook delivery request is invalid."""


@dataclass
class WebhookEndpoint:
    workspace_id: str
    url: str
    rate_limit: int = 60
    window_seconds: float = 60.0
    enabled: bool = True
    secret_version: int = 1
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class DeliveryRecord:
    endpoint_id: str
    workspace_id: str
    event_id: str
    status: str
    id: str = field(default_factory=lambda: str(uuid4()))
    error_code: Optional[str] = None
    retry_after: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    def public_view(self) -> Dict[str, Any]:
        return {
            key: value
            for key, value in {
                "id": self.id,
                "endpoint_id": self.endpoint_id,
                "workspace_id": self.workspace_id,
                "event_id": self.event_id,
                "status": self.status,
                "error_code": self.error_code,
                "retry_after": self.retry_after,
                "created_at": self.created_at,
            }.items()
            if value is not None
        }


class WebhookFanoutController:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._records: Dict[str, DeliveryRecord] = {}
        self._idempotency: Dict[Tuple[str, str, str], str] = {}
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._audit_events: List[Dict[str, Any]] = []

    def register_endpoint(
        self,
        workspace_id: str,
        url: str,
        endpoint_id: Optional[str] = None,
        rate_limit: int = 60,
        window_seconds: float = 60.0,
    ) -> WebhookEndpoint:
        self._validate_url(url)
        if rate_limit < 1:
            raise DeliveryControlError("rate_limit must be positive")
        if window_seconds <= 0:
            raise DeliveryControlError("window_seconds must be positive")
        endpoint = WebhookEndpoint(
            id=endpoint_id or str(uuid4()),
            workspace_id=workspace_id,
            url=url,
            rate_limit=rate_limit,
            window_seconds=window_seconds,
        )
        self._endpoints[endpoint.id] = endpoint
        return endpoint

    def disable_endpoint(self, workspace_id: str, endpoint_id: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint or endpoint.workspace_id != workspace_id:
            return False
        endpoint.enabled = False
        return True

    def rotate_secret(self, workspace_id: str, endpoint_id: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint or endpoint.workspace_id != workspace_id:
            return False
        endpoint.secret_version += 1
        return True

    def fanout(
        self,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        payload: Dict[str, Any],
        secret_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        key = (workspace_id, endpoint_id, event_id)
        existing = self._idempotency.get(key)
        if existing:
            self._audit("replayed", workspace_id, endpoint_id, event_id)
            return self._records[existing].public_view()

        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint or endpoint.workspace_id != workspace_id:
            return self._reject(
                key,
                workspace_id,
                endpoint_id,
                event_id,
                "endpoint_scope_mismatch",
            )
        if not endpoint.enabled:
            return self._reject(
                key,
                workspace_id,
                endpoint_id,
                event_id,
                "endpoint_disabled",
            )
        if (
            secret_version is not None
            and secret_version != endpoint.secret_version
        ):
            return self._reject(
                key,
                workspace_id,
                endpoint_id,
                event_id,
                "endpoint_secret_rotated",
            )

        retry_after = self._retry_after(endpoint)
        if retry_after is not None:
            return self._store(
                key,
                workspace_id,
                endpoint_id,
                event_id,
                "backpressure",
                error_code="rate_limited",
                retry_after=retry_after,
            )

        self._windows[endpoint.id].append(self._clock())
        self._audit("accepted", workspace_id, endpoint_id, event_id)
        return self._store(
            key,
            workspace_id,
            endpoint_id,
            event_id,
            "accepted",
        )

    def callback_payload(self, record_id: str) -> Dict[str, Any]:
        return self._records[record_id].public_view()

    def audit_report(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def _retry_after(self, endpoint: WebhookEndpoint) -> Optional[float]:
        now = self._clock()
        window = self._windows[endpoint.id]
        cutoff = now - endpoint.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) < endpoint.rate_limit:
            return None
        return max(0.0, endpoint.window_seconds - (now - window[0]))

    def _reject(
        self,
        key: Tuple[str, str, str],
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        error_code: str,
    ) -> Dict[str, Any]:
        self._audit(error_code, workspace_id, endpoint_id, event_id)
        return self._store(
            key,
            workspace_id,
            endpoint_id,
            event_id,
            "rejected",
            error_code=error_code,
        )

    def _store(
        self,
        key: Tuple[str, str, str],
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        status: str,
        error_code: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> Dict[str, Any]:
        record = DeliveryRecord(
            workspace_id=workspace_id,
            endpoint_id=endpoint_id,
            event_id=event_id,
            status=status,
            error_code=error_code,
            retry_after=retry_after,
            created_at=self._clock(),
        )
        self._records[record.id] = record
        self._idempotency[key] = record.id
        return record.public_view()

    def _audit(
        self,
        action: str,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
    ) -> None:
        self._audit_events.append(
            {
                "action": action,
                "workspace_id": workspace_id,
                "endpoint_id": endpoint_id,
                "event_id": event_id,
                "timestamp": self._clock(),
            }
        )

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise DeliveryControlError("webhook endpoint must be https")
