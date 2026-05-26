"""Webhook subscription API guards."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


ALLOWED_WEBHOOK_EVENTS = frozenset(
    {
        "agent.registered",
        "agent.started",
        "agent.stopped",
        "task.completed",
        "task.failed",
        "workflow.completed",
        "workflow.failed",
    }
)

INTERNAL_PAYLOAD_PREFIXES = ("_", "internal_")
INTERNAL_PAYLOAD_KEYS = {"secret", "signature", "token", "worker_id"}

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookSubscriptionCreate(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    endpoint_url: str = Field(..., min_length=1)
    event_types: List[str] = Field(..., min_length=1)
    disabled: bool = False


class WebhookSubscriptionUpdate(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    endpoint_url: Optional[str] = Field(default=None, min_length=1)
    event_types: Optional[List[str]] = None
    disabled: Optional[bool] = None


class WebhookDeliveryCreate(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    delivery_id: str = Field(default_factory=lambda: str(uuid4()))


@dataclass
class WebhookSubscription:
    workspace_id: str
    endpoint_url: str
    event_types: Tuple[str, ...]
    disabled: bool = False
    endpoint_version: int = 1
    id: str = field(default_factory=lambda: str(uuid4()))

    def public_view(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "endpoint_url": self.endpoint_url,
            "event_types": list(self.event_types),
            "disabled": self.disabled,
            "endpoint_version": self.endpoint_version,
        }


@dataclass
class WebhookDelivery:
    workspace_id: str
    subscription_id: str
    event_type: str
    delivery_id: str
    endpoint_version: int
    status: str
    payload: Dict[str, Any]
    error_code: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def public_view(self) -> Dict[str, Any]:
        view = {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "subscription_id": self.subscription_id,
            "event_type": self.event_type,
            "delivery_id": self.delivery_id,
            "endpoint_version": self.endpoint_version,
            "status": self.status,
            "payload": deepcopy(self.payload),
        }
        if self.error_code:
            view["error_code"] = self.error_code
        return view


class WebhookStore:
    def __init__(self) -> None:
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        self._deliveries: Dict[Tuple[str, str, str], WebhookDelivery] = {}

    def reset(self) -> None:
        self._subscriptions.clear()
        self._deliveries.clear()

    def create(
        self,
        request: WebhookSubscriptionCreate,
    ) -> WebhookSubscription:
        subscription = WebhookSubscription(
            workspace_id=request.workspace_id,
            endpoint_url=_validate_endpoint_url(request.endpoint_url),
            event_types=tuple(_validate_event_types(request.event_types)),
            disabled=request.disabled,
        )
        self._subscriptions[subscription.id] = subscription
        return subscription

    def update(
        self,
        subscription_id: str,
        request: WebhookSubscriptionUpdate,
    ) -> WebhookSubscription:
        subscription = self._get_for_workspace(
            subscription_id,
            request.workspace_id,
        )
        if request.event_types is not None:
            subscription.event_types = tuple(
                _validate_event_types(request.event_types)
            )
        if request.endpoint_url is not None:
            endpoint_url = _validate_endpoint_url(request.endpoint_url)
            if endpoint_url != subscription.endpoint_url:
                subscription.endpoint_url = endpoint_url
                subscription.endpoint_version += 1
        if request.disabled is not None:
            subscription.disabled = request.disabled
        return subscription

    def deliver(
        self,
        subscription_id: str,
        request: WebhookDeliveryCreate,
    ) -> WebhookDelivery:
        idempotency_key = (
            request.workspace_id,
            subscription_id,
            request.delivery_id,
        )
        if idempotency_key in self._deliveries:
            return self._deliveries[idempotency_key]

        subscription = self._subscriptions.get(subscription_id)
        if (
            not subscription
            or subscription.workspace_id != request.workspace_id
        ):
            delivery = self._rejected(
                subscription_id,
                request,
                0,
                "subscription_scope_mismatch",
            )
        elif subscription.disabled:
            delivery = self._rejected(
                subscription_id,
                request,
                subscription.endpoint_version,
                "subscription_disabled",
            )
        elif request.event_type not in subscription.event_types:
            delivery = self._rejected(
                subscription_id,
                request,
                subscription.endpoint_version,
                "event_not_subscribed",
            )
        else:
            delivery = WebhookDelivery(
                workspace_id=request.workspace_id,
                subscription_id=subscription_id,
                event_type=request.event_type,
                delivery_id=request.delivery_id,
                endpoint_version=subscription.endpoint_version,
                status="queued",
                payload=_sanitize_payload(request.payload),
            )

        self._deliveries[idempotency_key] = delivery
        return delivery

    def _get_for_workspace(
        self,
        subscription_id: str,
        workspace_id: str,
    ) -> WebhookSubscription:
        subscription = self._subscriptions.get(subscription_id)
        if not subscription or subscription.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Webhook not found")
        return subscription

    @staticmethod
    def _rejected(
        subscription_id: str,
        request: WebhookDeliveryCreate,
        endpoint_version: int,
        error_code: str,
    ) -> WebhookDelivery:
        return WebhookDelivery(
            workspace_id=request.workspace_id,
            subscription_id=subscription_id,
            event_type=request.event_type,
            delivery_id=request.delivery_id,
            endpoint_version=endpoint_version,
            status="rejected",
            payload={},
            error_code=error_code,
        )


store = WebhookStore()


@router.post("")
async def create_webhook(
    request: WebhookSubscriptionCreate,
) -> Dict[str, Any]:
    return store.create(request).public_view()


@router.patch("/{subscription_id}")
async def update_webhook(
    subscription_id: str,
    request: WebhookSubscriptionUpdate,
) -> Dict[str, Any]:
    return store.update(subscription_id, request).public_view()


@router.post("/{subscription_id}/deliveries")
async def create_delivery(
    subscription_id: str,
    request: WebhookDeliveryCreate,
) -> Dict[str, Any]:
    return store.deliver(subscription_id, request).public_view()


def _validate_endpoint_url(endpoint_url: str) -> str:
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="endpoint_url must be an absolute HTTP(S) URL",
        )
    return endpoint_url


def _validate_event_types(event_types: List[str]) -> List[str]:
    normalized: List[str] = []
    invalid: List[str] = []
    for event_type in event_types:
        event_type = event_type.strip() if isinstance(event_type, str) else ""
        if event_type not in ALLOWED_WEBHOOK_EVENTS:
            invalid.append(event_type)
            continue
        if event_type not in normalized:
            normalized.append(event_type)
    if invalid or not normalized:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "event_types must use the webhook allowlist",
                "allowed": sorted(ALLOWED_WEBHOOK_EVENTS),
                "invalid": invalid,
            },
        )
    return normalized


def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in INTERNAL_PAYLOAD_KEYS
        and not key.startswith(INTERNAL_PAYLOAD_PREFIXES)
    }
