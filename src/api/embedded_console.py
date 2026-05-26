"""Embedded admin console session exchange guards."""

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set
from uuid import uuid4

import jwt


class EmbeddedConsoleAuthError(ValueError):
    """Raised when an embedded console token cannot mint a session."""


@dataclass(frozen=True)
class EmbeddedConsoleIssuer:
    issuer: str
    secret: str
    audience: str
    allowed_tenants: Set[str] = field(default_factory=set)
    algorithms: List[str] = field(default_factory=lambda: ["HS256"])


@dataclass
class EmbeddedConsoleSession:
    id: str
    tenant_id: str
    issuer: str
    subject: str
    audience: str
    created_at: float
    expires_at: float

    def public_view(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "issuer": self.issuer,
            "subject": self.subject,
            "audience": self.audience,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


class EmbeddedConsoleSessionExchange:
    def __init__(
        self,
        issuers: List[EmbeddedConsoleIssuer],
        clock: Callable[[], float] = time.time,
        max_session_ttl: int = 900,
    ):
        self._issuers = {issuer.issuer: issuer for issuer in issuers}
        self._clock = clock
        self.max_session_ttl = max_session_ttl
        self._sessions: Dict[str, EmbeddedConsoleSession] = {}
        self._audit_events: List[Dict[str, object]] = []

    def exchange(self, token: str, tenant_id: str) -> EmbeddedConsoleSession:
        if not tenant_id:
            raise EmbeddedConsoleAuthError("tenant_id is required")

        issuer_name = self._unverified_issuer(token)
        issuer = self._issuers.get(issuer_name)
        if not issuer:
            self._reject("unknown_issuer", tenant_id, issuer_name)
            raise EmbeddedConsoleAuthError("issuer is not trusted")

        try:
            claims = jwt.decode(
                token,
                issuer.secret,
                algorithms=issuer.algorithms,
                audience=issuer.audience,
                issuer=issuer.issuer,
                options={
                    "require": ["aud", "exp", "iss", "sub", "tenant_id"],
                    "verify_exp": False,
                },
            )
        except jwt.InvalidAudienceError as exc:
            self._reject("invalid_audience", tenant_id, issuer.issuer)
            raise EmbeddedConsoleAuthError("invalid audience") from exc
        except jwt.InvalidIssuerError as exc:
            self._reject("invalid_issuer", tenant_id, issuer.issuer)
            raise EmbeddedConsoleAuthError("invalid issuer") from exc
        except jwt.PyJWTError as exc:
            self._reject("invalid_token", tenant_id, issuer.issuer)
            raise EmbeddedConsoleAuthError("invalid token") from exc

        token_tenant = claims["tenant_id"]
        if token_tenant != tenant_id:
            self._reject("tenant_mismatch", tenant_id, issuer.issuer)
            raise EmbeddedConsoleAuthError("tenant mismatch")
        if issuer.allowed_tenants and tenant_id not in issuer.allowed_tenants:
            self._reject("tenant_not_allowed", tenant_id, issuer.issuer)
            raise EmbeddedConsoleAuthError("tenant is not allowed")

        now = self._clock()
        if float(claims["exp"]) <= now:
            self._reject("token_expired", tenant_id, issuer.issuer)
            raise EmbeddedConsoleAuthError("token expired")
        expires_at = min(float(claims["exp"]), now + self.max_session_ttl)
        session = EmbeddedConsoleSession(
            id=str(uuid4()),
            tenant_id=tenant_id,
            issuer=issuer.issuer,
            subject=claims["sub"],
            audience=issuer.audience,
            created_at=now,
            expires_at=expires_at,
        )
        self._sessions[session.id] = session
        self._audit(
            "session_created",
            tenant_id,
            issuer.issuer,
            {"session_id": session.id, "subject": session.subject},
        )
        return session

    def get_session(self, session_id: str) -> Optional[EmbeddedConsoleSession]:
        return self._sessions.get(session_id)

    def audit_report(self) -> List[Dict[str, object]]:
        return [dict(event) for event in self._audit_events]

    def _unverified_issuer(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_exp": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise EmbeddedConsoleAuthError("invalid token") from exc
        return str(claims.get("iss", ""))

    def _reject(self, reason: str, tenant_id: str, issuer: str) -> None:
        self._audit("session_rejected", tenant_id, issuer, {"reason": reason})

    def _audit(
        self,
        action: str,
        tenant_id: str,
        issuer: str,
        details: Dict[str, object],
    ) -> None:
        self._audit_events.append(
            {
                "action": action,
                "tenant_id": tenant_id,
                "issuer": issuer,
                "details": dict(details),
                "timestamp": self._clock(),
            }
        )
