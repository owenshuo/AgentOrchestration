"""Webhook endpoint ownership and secret rotation guards."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


class WebhookSecurityError(ValueError):
    """Raised when a webhook operation violates endpoint ownership policy."""


@dataclass(frozen=True)
class WebhookPrincipal:
    principal_id: str
    workspace_id: str
    roles: Set[str] = field(default_factory=set)
    active: bool = True


@dataclass
class WebhookEndpoint:
    endpoint_id: str
    workspace_id: str
    owner_id: str
    url: str
    secret_version: int = 1
    enabled: bool = True
    _secret: str = ""


class WebhookSecretStore:
    """Scopes webhook endpoint secrets to the caller workspace and role."""

    _MUTATION_ROLES = {"owner", "admin"}

    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._delivery_records: Dict[str, Dict[str, Any]] = {}
        self._audit_events: List[Dict[str, Any]] = []

    def register_endpoint(
        self,
        principal: WebhookPrincipal,
        url: str,
        secret: str,
    ) -> WebhookEndpoint:
        self._require_mutation_access(principal)
        endpoint = WebhookEndpoint(
            endpoint_id=str(uuid4()),
            workspace_id=principal.workspace_id,
            owner_id=principal.principal_id,
            url=self._require_text("url", url),
            _secret=self._require_text("secret", secret),
        )
        self._endpoints[endpoint.endpoint_id] = endpoint
        self._record_audit("register", "allow", endpoint, principal)
        return self._public_endpoint(endpoint)

    def rotate_secret(
        self,
        principal: WebhookPrincipal,
        endpoint_id: str,
        new_secret: str,
    ) -> WebhookEndpoint:
        endpoint = self._get_owned_endpoint(principal, endpoint_id)
        self._require_mutation_access(principal)
        endpoint._secret = self._require_text("secret", new_secret)
        endpoint.secret_version += 1
        self._record_audit("rotate_secret", "allow", endpoint, principal)
        return self._public_endpoint(endpoint)

    def disable_endpoint(
        self,
        principal: WebhookPrincipal,
        endpoint_id: str,
    ) -> WebhookEndpoint:
        endpoint = self._get_owned_endpoint(principal, endpoint_id)
        self._require_mutation_access(principal)
        endpoint.enabled = False
        self._record_audit("disable", "allow", endpoint, principal)
        return self._public_endpoint(endpoint)

    def deliver(
        self,
        principal: WebhookPrincipal,
        endpoint_id: str,
        event: Dict[str, Any],
        idempotency_key: str,
        secret_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        endpoint = self._get_owned_endpoint(principal, endpoint_id)
        key = self._require_text("idempotency_key", idempotency_key)
        if key in self._delivery_records:
            return dict(self._delivery_records[key])
        if not endpoint.enabled:
            self._record_audit("deliver", "deny_disabled", endpoint, principal)
            raise WebhookSecurityError("webhook endpoint is disabled")
        if (
            secret_version is not None
            and secret_version != endpoint.secret_version
        ):
            self._record_audit(
                "deliver",
                "deny_stale_secret",
                endpoint,
                principal,
            )
            raise WebhookSecurityError("webhook secret has rotated")

        record = {
            "delivery_id": str(uuid4()),
            "endpoint_id": endpoint.endpoint_id,
            "workspace_id": endpoint.workspace_id,
            "event_type": self._require_text("event_type", event.get("type")),
            "attempts": 1,
            "status": "queued",
        }
        self._delivery_records[key] = dict(record)
        self._record_audit("deliver", "allow", endpoint, principal)
        return dict(record)

    @property
    def audit_events(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def audit_report(self) -> Dict[str, Any]:
        return {
            "total": len(self._audit_events),
            "by_operation": self._count_by("operation"),
            "by_decision": self._count_by("decision"),
            "recent": self.audit_events,
        }

    def _get_owned_endpoint(
        self,
        principal: WebhookPrincipal,
        endpoint_id: str,
    ) -> WebhookEndpoint:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise WebhookSecurityError("webhook endpoint not found")
        if not principal.active:
            self._record_audit(
                "endpoint_scope",
                "deny_inactive",
                endpoint,
                principal,
            )
            raise WebhookSecurityError("principal is inactive")
        if principal.workspace_id != endpoint.workspace_id:
            self._record_audit(
                "endpoint_scope",
                "deny_workspace",
                endpoint,
                principal,
            )
            raise WebhookSecurityError(
                "webhook endpoint belongs to another workspace"
            )
        return endpoint

    def _require_mutation_access(self, principal: WebhookPrincipal) -> None:
        if not principal.active:
            raise WebhookSecurityError("principal is inactive")
        if not principal.workspace_id:
            raise WebhookSecurityError("workspace scope is required")
        if not principal.roles.intersection(self._MUTATION_ROLES):
            raise WebhookSecurityError(
                "webhook endpoint owner role is required"
            )

    def _record_audit(
        self,
        operation: str,
        decision: str,
        endpoint: WebhookEndpoint,
        principal: WebhookPrincipal,
    ) -> None:
        self._audit_events.append(
            {
                "operation": operation,
                "decision": decision,
                "endpoint_id": endpoint.endpoint_id,
                "workspace_id": endpoint.workspace_id,
                "principal_id": principal.principal_id,
                "secret_version": endpoint.secret_version,
            }
        )

    def _count_by(self, field_name: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for event in self._audit_events:
            key = str(event[field_name])
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _public_endpoint(endpoint: WebhookEndpoint) -> WebhookEndpoint:
        return WebhookEndpoint(
            endpoint_id=endpoint.endpoint_id,
            workspace_id=endpoint.workspace_id,
            owner_id=endpoint.owner_id,
            url=endpoint.url,
            secret_version=endpoint.secret_version,
            enabled=endpoint.enabled,
            _secret="",
        )

    @staticmethod
    def _require_text(field_name: str, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise WebhookSecurityError(f"{field_name} is required")
        return value.strip()
