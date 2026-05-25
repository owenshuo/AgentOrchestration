"""Webhook endpoint validation and idempotent delivery records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Set


class EndpointState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    REVOKED = "revoked"
    EXPIRED = "expired"


class WebhookDeliveryStateError(ValueError):
    """Raised when delivery state blocks a webhook event."""


@dataclass
class WebhookEndpoint:
    endpoint_id: str
    workspace_id: str
    url: str
    state: EndpointState = EndpointState.ENABLED
    generation: int = 1


@dataclass(frozen=True)
class DeliveryRecord:
    event_id: str
    endpoint_id: str
    workspace_id: str
    status: str
    attempt: int
    callback_payload: Dict[str, Any] = field(default_factory=dict)


class WebhookDeliveryService:
    def __init__(self):
        self._endpoints: Dict[tuple[str, str], WebhookEndpoint] = {}
        self._records: Dict[tuple[str, str, int], DeliveryRecord] = {}
        self.audit_records: list[Dict[str, Any]] = []

    def register_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
        url: str,
        state: EndpointState = EndpointState.ENABLED,
        generation: int = 1,
    ) -> None:
        self._endpoints[(workspace_id, endpoint_id)] = WebhookEndpoint(
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            url=url,
            state=state,
            generation=generation,
        )

    def set_endpoint_state(
        self,
        endpoint_id: str,
        workspace_id: str,
        state: EndpointState,
    ) -> None:
        endpoint = self._lookup_endpoint(endpoint_id, workspace_id)
        endpoint.state = state

    def deliver(
        self,
        event: Mapping[str, Any],
        endpoint_id: str,
        workspace_id: str,
        attempt: int = 1,
    ) -> DeliveryRecord:
        endpoint = self._lookup_endpoint(endpoint_id, workspace_id)
        self._validate_endpoint(endpoint, event)
        key = (str(event["event_id"]), endpoint_id, attempt)
        if key in self._records:
            return self._records[key]

        payload = self._external_payload(event)
        record = DeliveryRecord(
            event_id=str(event["event_id"]),
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            status="delivered",
            attempt=attempt,
            callback_payload=payload,
        )
        self._records[key] = record
        return record

    def retry(
        self,
        event: Mapping[str, Any],
        endpoint_id: str,
        workspace_id: str,
        attempt: int,
    ) -> DeliveryRecord:
        endpoint = self._lookup_endpoint(endpoint_id, workspace_id)
        try:
            self._validate_endpoint(endpoint, event)
        except WebhookDeliveryStateError as error:
            record = DeliveryRecord(
                event_id=str(event["event_id"]),
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
                status="permanently_failed",
                attempt=attempt,
            )
            self._records[(record.event_id, endpoint_id, attempt)] = record
            self.audit_records.append(
                {
                    "event_id": record.event_id,
                    "endpoint_id": endpoint_id,
                    "workspace_id": workspace_id,
                    "decision": "retry_blocked",
                    "reason": str(error),
                }
            )
            return record
        return self.deliver(event, endpoint_id, workspace_id, attempt)

    def _lookup_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
    ) -> WebhookEndpoint:
        endpoint = self._endpoints.get((workspace_id, endpoint_id))
        if endpoint is None:
            raise WebhookDeliveryStateError("endpoint not found in workspace")
        return endpoint

    def _validate_endpoint(
        self,
        endpoint: WebhookEndpoint,
        event: Mapping[str, Any],
    ) -> None:
        if endpoint.state is not EndpointState.ENABLED:
            raise WebhookDeliveryStateError(
                f"endpoint is {endpoint.state.value}"
            )
        if str(event.get("workspace_id")) != endpoint.workspace_id:
            raise WebhookDeliveryStateError("workspace isolation violation")
        if int(event.get("endpoint_generation", endpoint.generation)) != (
            endpoint.generation
        ):
            raise WebhookDeliveryStateError("endpoint generation is stale")

    def _external_payload(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        internal_fields: Set[str] = {
            "internal_trace",
            "internal_retry_state",
            "secret",
            "endpoint_generation",
        }
        return {
            key: value
            for key, value in event.items()
            if key not in internal_fields
        }
