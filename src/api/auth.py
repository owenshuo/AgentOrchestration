"""Authentication helpers for API middleware."""

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


class AuthenticationError(ValueError):
    """Raised when request credentials fail closed."""


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace: str
    role: str
    scopes: frozenset[str]


def validate_worker_token(
    token: str,
    now: Optional[float] = None,
    required_scope: str = "worker:request",
) -> Principal:
    claims = _decode_claims(token)
    current_time = time.time() if now is None else now

    subject = str(claims.get("sub") or "").strip()
    if not subject or claims.get("anonymous"):
        raise AuthenticationError("anonymous principal is not allowed")

    if claims.get("revoked"):
        raise AuthenticationError("revoked credential is not allowed")

    not_before = _numeric_claim(claims, "nbf")
    if not_before is not None and current_time < not_before:
        raise AuthenticationError("credential is not valid yet")

    expires_at = _numeric_claim(claims, "exp")
    if expires_at is not None and current_time >= expires_at:
        raise AuthenticationError("credential has expired")

    workspace = str(claims.get("workspace") or "").strip()
    if not workspace:
        raise AuthenticationError("workspace claim is required")

    role = str(claims.get("role") or "").strip()
    scopes = frozenset(_normalize_scopes(claims.get("scopes", ())))
    if required_scope not in scopes and role not in {"worker", "admin"}:
        raise AuthenticationError("credential has insufficient scope")

    return Principal(
        subject=subject,
        workspace=workspace,
        role=role,
        scopes=scopes,
    )


def _decode_claims(token: str) -> Dict[str, Any]:
    token = token.strip()
    if not token:
        raise AuthenticationError("missing token")

    payload = token.split(".")[1] if token.count(".") == 2 else token
    try:
        if payload.startswith("{"):
            claims = json.loads(payload)
        else:
            claims = json.loads(_base64url_decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise AuthenticationError("malformed token") from error

    if not isinstance(claims, dict):
        raise AuthenticationError("malformed token claims")
    return claims


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _numeric_claim(claims: Dict[str, Any], name: str) -> Optional[float]:
    value = claims.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise AuthenticationError(f"{name} claim must be numeric") from error


def _normalize_scopes(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        return [scope for scope in value.split() if scope]
    if isinstance(value, (list, tuple, set)):
        return [str(scope) for scope in value if scope]
    return []
