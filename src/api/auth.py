"""Authorization helpers for collaboration API actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Optional, Set


class AuthDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class WorkspaceRole(str, Enum):
    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    id: str
    workspace_id: Optional[str]
    roles: Set[WorkspaceRole] = field(default_factory=set)
    authenticated: bool = True
    revoked: bool = False
    stale: bool = False


@dataclass(frozen=True)
class SavedViewShareRequest:
    workspace_id: str
    view_id: str
    target_principal_id: str


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthDecision
    reason: str
    audit: Dict[str, str]

    @property
    def allowed(self) -> bool:
        return self.decision == AuthDecision.ALLOW


class CollaborationAuthService:
    """Central membership and role guard for collaboration actions."""

    _SHARE_ROLES = {WorkspaceRole.MEMBER, WorkspaceRole.ADMIN}

    def authorize_saved_view_share(
        self,
        principal: Optional[Principal],
        request: SavedViewShareRequest,
    ) -> AuthorizationResult:
        if principal is None or not principal.authenticated:
            return self._deny("anonymous_principal", principal, request)
        if principal.revoked:
            return self._deny("revoked_principal", principal, request)
        if principal.stale:
            return self._deny("stale_principal", principal, request)
        if principal.workspace_id != request.workspace_id:
            return self._deny(
                "workspace_membership_required",
                principal,
                request,
            )
        if not self._has_any_role(principal.roles, self._SHARE_ROLES):
            return self._deny(
                "insufficient_workspace_role",
                principal,
                request,
            )
        return AuthorizationResult(
            decision=AuthDecision.ALLOW,
            reason="authorized",
            audit=self._audit("allow", "authorized", principal, request),
        )

    @staticmethod
    def _has_any_role(
        roles: Iterable[WorkspaceRole],
        allowed_roles: Set[WorkspaceRole],
    ) -> bool:
        return bool(set(roles).intersection(allowed_roles))

    def _deny(
        self,
        reason: str,
        principal: Optional[Principal],
        request: SavedViewShareRequest,
    ) -> AuthorizationResult:
        return AuthorizationResult(
            decision=AuthDecision.DENY,
            reason=reason,
            audit=self._audit("deny", reason, principal, request),
        )

    @staticmethod
    def _audit(
        decision: str,
        reason: str,
        principal: Optional[Principal],
        request: SavedViewShareRequest,
    ) -> Dict[str, str]:
        audit = {
            "decision": decision,
            "reason": reason,
            "workspace_id": request.workspace_id,
            "view_id": request.view_id,
        }
        if principal is not None:
            audit["principal_id"] = principal.id
        return audit
