"""Authorization guard for live-update websocket token minting."""

import secrets
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Set


class LiveUpdateAuthError(PermissionError):
    """Raised when a live-update websocket token must not be minted."""


@dataclass(frozen=True)
class LiveUpdateCredential:
    principal_id: str
    workspace_id: str
    roles: Set[str] = field(default_factory=set)
    scopes: Set[str] = field(default_factory=set)
    expires_at: float = 0.0
    not_before: float = 0.0
    revoked: bool = False


@dataclass(frozen=True)
class LiveUpdateWebsocketToken:
    token: str
    principal_id: str
    workspace_id: str
    expires_at: float

    def public_view(self) -> Dict[str, object]:
        return {
            "token": self.token,
            "principal_id": self.principal_id,
            "workspace_id": self.workspace_id,
            "expires_at": self.expires_at,
        }


class LiveUpdateAuthService:
    REQUIRED_SCOPE = "live_updates:mint"
    ALLOWED_ROLES = {"admin", "operator", "owner"}

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        token_ttl: float = 300.0,
    ):
        self._clock = clock
        self.token_ttl = token_ttl
        self._bearer_credentials: Dict[str, LiveUpdateCredential] = {}
        self._browser_credentials: Dict[str, LiveUpdateCredential] = {}
        self._minted_tokens: Dict[str, LiveUpdateWebsocketToken] = {}
        self._audit_events: List[Dict[str, object]] = []

    def register_bearer(
        self,
        token: str,
        credential: LiveUpdateCredential,
    ) -> None:
        self._bearer_credentials[token] = credential

    def register_browser_session(
        self,
        session_id: str,
        credential: LiveUpdateCredential,
    ) -> None:
        self._browser_credentials[session_id] = credential

    def revoke_bearer(self, token: str) -> None:
        credential = self._bearer_credentials.get(token)
        if credential:
            self._bearer_credentials[token] = self._revoked(credential)

    def revoke_browser_session(self, session_id: str) -> None:
        credential = self._browser_credentials.get(session_id)
        if credential:
            self._browser_credentials[session_id] = self._revoked(credential)

    def mint(
        self,
        workspace_id: str,
        authorization_header: str = "",
        browser_session: str = "",
    ) -> LiveUpdateWebsocketToken:
        credential = self._credential_from_request(
            authorization_header,
            browser_session,
        )
        self._validate_credential(credential, workspace_id)

        token = LiveUpdateWebsocketToken(
            token=f"wss_{secrets.token_urlsafe(32)}",
            principal_id=credential.principal_id,
            workspace_id=workspace_id,
            expires_at=self._clock() + self.token_ttl,
        )
        self._minted_tokens[token.token] = token
        self._audit(
            "websocket_token_minted",
            workspace_id,
            credential.principal_id,
            {},
        )
        return token

    def audit_report(self) -> List[Dict[str, object]]:
        return [dict(event) for event in self._audit_events]

    def reset(self) -> None:
        self._bearer_credentials.clear()
        self._browser_credentials.clear()
        self._minted_tokens.clear()
        self._audit_events.clear()

    def _credential_from_request(
        self,
        authorization_header: str,
        browser_session: str,
    ) -> LiveUpdateCredential:
        if authorization_header.startswith("Bearer "):
            token = authorization_header.split(" ", 1)[1]
            credential = self._bearer_credentials.get(token)
            if credential:
                return credential
            self._reject("unknown_bearer", "", "")
            raise LiveUpdateAuthError("invalid bearer token")
        if browser_session:
            credential = self._browser_credentials.get(browser_session)
            if credential:
                return credential
            self._reject("unknown_browser_session", "", "")
            raise LiveUpdateAuthError("invalid browser session")
        self._reject("anonymous", "", "")
        raise LiveUpdateAuthError("authentication required")

    def _validate_credential(
        self,
        credential: LiveUpdateCredential,
        workspace_id: str,
    ) -> None:
        now = self._clock()
        if credential.revoked:
            self._reject("revoked", workspace_id, credential.principal_id)
            raise LiveUpdateAuthError("credential revoked")
        if credential.not_before and now < credential.not_before:
            self._reject("not_before", workspace_id, credential.principal_id)
            raise LiveUpdateAuthError("credential not active")
        if credential.expires_at and now >= credential.expires_at:
            self._reject("expired", workspace_id, credential.principal_id)
            raise LiveUpdateAuthError("credential expired")
        if credential.workspace_id != workspace_id:
            self._reject(
                "workspace_mismatch",
                workspace_id,
                credential.principal_id,
            )
            raise LiveUpdateAuthError("workspace mismatch")
        if self.REQUIRED_SCOPE not in credential.scopes:
            self._reject(
                "missing_scope",
                workspace_id,
                credential.principal_id,
            )
            raise LiveUpdateAuthError("insufficient scope")
        if not credential.roles.intersection(self.ALLOWED_ROLES):
            self._reject("missing_role", workspace_id, credential.principal_id)
            raise LiveUpdateAuthError("insufficient role")

    def _reject(
        self,
        reason: str,
        workspace_id: str,
        principal_id: str,
    ) -> None:
        self._audit(
            "websocket_token_rejected",
            workspace_id,
            principal_id,
            {"reason": reason},
        )

    def _audit(
        self,
        action: str,
        workspace_id: str,
        principal_id: str,
        details: Dict[str, object],
    ) -> None:
        self._audit_events.append(
            {
                "action": action,
                "workspace_id": workspace_id,
                "principal_id": principal_id,
                "details": dict(details),
                "timestamp": self._clock(),
            }
        )

    def _revoked(
        self,
        credential: LiveUpdateCredential,
    ) -> LiveUpdateCredential:
        return LiveUpdateCredential(
            principal_id=credential.principal_id,
            workspace_id=credential.workspace_id,
            roles=set(credential.roles),
            scopes=set(credential.scopes),
            expires_at=credential.expires_at,
            not_before=credential.not_before,
            revoked=True,
        )
