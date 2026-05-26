"""Outbound connector host allowlist policy."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List
from urllib.parse import unquote, urlparse


class OutboundRequestPolicyError(ValueError):
    """Raised when an outbound request violates connector policy."""


@dataclass(frozen=True)
class OutboundRequestDecision:
    allowed: bool
    normalized_host: str
    reason: str


def canonicalize_hostname(hostname: str) -> str:
    """Normalize hostnames before security policy comparison."""
    if not hostname:
        raise OutboundRequestPolicyError("hostname is required")

    decoded = unquote(hostname).strip().rstrip(".").lower()
    if not decoded:
        raise OutboundRequestPolicyError("hostname is required")
    if "/" in decoded or "\\" in decoded or "@" in decoded:
        raise OutboundRequestPolicyError(
            "hostname contains invalid characters",
        )

    try:
        ascii_host = decoded.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise OutboundRequestPolicyError(
            "hostname is not valid IDNA",
        ) from error

    return ascii_host.rstrip(".").lower()


class OutboundRequestPolicy:
    """Evaluates outbound connector targets before network dispatch."""

    def __init__(self, allowed_hosts: Iterable[str]):
        self._allowed_hosts = {
            canonicalize_hostname(host)
            for host in allowed_hosts
        }
        self._audit_events: List[Dict[str, Any]] = []

    @property
    def audit_events(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def evaluate(self, url: str) -> OutboundRequestDecision:
        parsed = urlparse(url)
        host = parsed.hostname
        normalized_host = canonicalize_hostname(host or "")
        allowed = normalized_host in self._allowed_hosts
        reason = "allowed" if allowed else "host_not_allowed"
        self._audit_events.append(
            {
                "url_scheme": parsed.scheme,
                "normalized_host": normalized_host,
                "allowed": allowed,
                "reason": reason,
            }
        )
        return OutboundRequestDecision(
            allowed=allowed,
            normalized_host=normalized_host,
            reason=reason,
        )

    def dispatch(
        self,
        url: str,
        dispatcher: Callable[[str], Any],
    ) -> Any:
        decision = self.evaluate(url)
        if not decision.allowed:
            raise OutboundRequestPolicyError(
                f"outbound host not allowed: {decision.normalized_host}",
            )
        return dispatcher(url)

    def is_allowed(self, url: str) -> bool:
        return self.evaluate(url).allowed
