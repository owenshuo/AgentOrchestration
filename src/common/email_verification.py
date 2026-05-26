"""Verified email canonicalization and duplicate-claim enforcement."""

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set


class EmailVerificationError(ValueError):
    """Raised when a verified email claim cannot be accepted."""


@dataclass(frozen=True)
class EmailCanonicalForm:
    original_domain: str
    canonical: str
    provider: str
    ignored_alias_parts: Set[str] = field(default_factory=set)

    def public_policy(self) -> Dict[str, object]:
        return {
            "canonical": self.canonical,
            "provider": self.provider,
            "ignored_alias_parts": sorted(self.ignored_alias_parts),
        }


@dataclass
class EmailClaim:
    user_id: str
    canonical_email: str
    provider: str
    verified_at: float
    last_seen_at: float
    claim_count: int = 1

    def public_view(self) -> Dict[str, object]:
        return {
            "user_id": self.user_id,
            "canonical_email": self.canonical_email,
            "provider": self.provider,
            "verified_at": self.verified_at,
            "last_seen_at": self.last_seen_at,
            "claim_count": self.claim_count,
        }


GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
OUTLOOK_DOMAINS = {"hotmail.com", "live.com", "msn.com", "outlook.com"}


def canonicalize_verified_email(email: str) -> EmailCanonicalForm:
    if not isinstance(email, str):
        raise EmailVerificationError("email must be a string")
    normalized = email.strip()
    if normalized.count("@") != 1:
        raise EmailVerificationError("email must contain exactly one @")

    local, domain = [part.strip().lower() for part in normalized.split("@", 1)]
    if not local or not domain:
        raise EmailVerificationError("email local and domain are required")
    if any(character.isspace() for character in f"{local}{domain}"):
        raise EmailVerificationError("email cannot contain whitespace")

    ignored_alias_parts: Set[str] = set()
    provider = "generic"
    canonical_domain = domain
    canonical_local = local

    if domain in GMAIL_DOMAINS:
        provider = "gmail"
        canonical_domain = "gmail.com"
        if "." in canonical_local:
            ignored_alias_parts.add("dots")
        canonical_local = canonical_local.replace(".", "")
        if "+" in canonical_local:
            ignored_alias_parts.add("plus_tag")
            canonical_local = canonical_local.split("+", 1)[0]
    elif domain in OUTLOOK_DOMAINS:
        provider = "outlook"
        if "+" in canonical_local:
            ignored_alias_parts.add("plus_tag")
            canonical_local = canonical_local.split("+", 1)[0]

    if not canonical_local:
        raise EmailVerificationError("email local and domain are required")

    return EmailCanonicalForm(
        original_domain=domain,
        canonical=f"{canonical_local}@{canonical_domain}",
        provider=provider,
        ignored_alias_parts=ignored_alias_parts,
    )


class VerifiedEmailClaimStore:
    """Stores verified email claims keyed by provider canonical form."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._claims: Dict[str, EmailClaim] = {}
        self._user_claims: Dict[str, Set[str]] = {}
        self._audit_events: List[Dict[str, object]] = []

    def claim(self, user_id: str, email: str) -> EmailClaim:
        if not user_id:
            raise EmailVerificationError("user_id is required")
        canonical = canonicalize_verified_email(email)
        existing = self._claims.get(canonical.canonical)
        now = self._clock()

        if existing and existing.user_id != user_id:
            self._audit(
                "duplicate_rejected",
                user_id,
                canonical,
                {"owner_user_id": existing.user_id},
            )
            raise EmailVerificationError("verified email already claimed")

        if existing:
            existing.last_seen_at = now
            existing.claim_count += 1
            self._audit("claim_refreshed", user_id, canonical, {})
            return existing

        claim = EmailClaim(
            user_id=user_id,
            canonical_email=canonical.canonical,
            provider=canonical.provider,
            verified_at=now,
            last_seen_at=now,
        )
        self._claims[canonical.canonical] = claim
        self._user_claims.setdefault(user_id, set()).add(canonical.canonical)
        self._audit("claim_created", user_id, canonical, {})
        return claim

    def owner_for(self, email: str) -> Optional[str]:
        canonical = canonicalize_verified_email(email)
        claim = self._claims.get(canonical.canonical)
        return claim.user_id if claim else None

    def revoke(self, user_id: str, email: str) -> bool:
        canonical = canonicalize_verified_email(email)
        claim = self._claims.get(canonical.canonical)
        if not claim or claim.user_id != user_id:
            return False
        self._claims.pop(canonical.canonical)
        self._user_claims.get(user_id, set()).discard(canonical.canonical)
        self._audit("claim_revoked", user_id, canonical, {})
        return True

    def audit_report(self) -> List[Dict[str, object]]:
        return [dict(event) for event in self._audit_events]

    def _audit(
        self,
        action: str,
        user_id: str,
        canonical: EmailCanonicalForm,
        details: Dict[str, object],
    ) -> None:
        self._audit_events.append(
            {
                "action": action,
                "user_id": user_id,
                "canonical_email": canonical.canonical,
                "provider": canonical.provider,
                "ignored_alias_parts": sorted(canonical.ignored_alias_parts),
                "details": dict(details),
                "timestamp": self._clock(),
            }
        )
