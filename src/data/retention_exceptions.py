"""Retention exception registry with owner-aware governance validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional


class RetentionExceptionValidationError(ValueError):
    """Raised when a retention exception fails governance validation."""


@dataclass(frozen=True)
class RetentionException:
    category: str
    owner: str
    reason: str
    expires_at: date
    review_at: date

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "RetentionException":
        return cls(
            category=str(data.get("category", "")).strip(),
            owner=str(data.get("owner", "")).strip(),
            reason=str(data.get("reason", "")).strip(),
            expires_at=_parse_date(data.get("expires_at")),
            review_at=_parse_date(data.get("review_at")),
        )

    def validate(self, today: Optional[date] = None) -> None:
        today = today or _today()
        missing = [
            field
            for field, value in (
                ("category", self.category),
                ("owner", self.owner),
                ("reason", self.reason),
                ("expires_at", self.expires_at),
                ("review_at", self.review_at),
            )
            if not value
        ]
        if missing:
            raise RetentionExceptionValidationError(
                "Retention exception missing required metadata: "
                + ", ".join(missing)
            )
        if self.expires_at < today:
            raise RetentionExceptionValidationError(
                f"Retention exception for {self.category} expired on "
                f"{self.expires_at.isoformat()}"
            )
        if self.review_at > self.expires_at:
            raise RetentionExceptionValidationError(
                f"Retention exception for {self.category} has review date "
                "after expiration"
            )

    def is_active(self, today: Optional[date] = None) -> bool:
        self.validate(today=today)
        return True

    def to_report_entry(self) -> Dict[str, str]:
        return {
            "category": self.category,
            "reason": self.reason,
            "expires_at": self.expires_at.isoformat(),
            "review_at": self.review_at.isoformat(),
        }


class RetentionExceptionRegistry:
    def __init__(
        self,
        exceptions: Optional[Iterable[RetentionException]] = None,
    ):
        self._exceptions: List[RetentionException] = list(exceptions or [])

    def add(
        self,
        exception: RetentionException,
        today: Optional[date] = None,
    ) -> None:
        exception.validate(today=today)
        self._exceptions.append(exception)

    def validate(self, today: Optional[date] = None) -> None:
        for exception in self._exceptions:
            exception.validate(today=today)

    def active_by_owner(
        self,
        today: Optional[date] = None,
    ) -> Dict[str, List[Dict[str, str]]]:
        today = today or _today()
        grouped: Dict[str, List[Dict[str, str]]] = {}
        for exception in self._exceptions:
            if not exception.is_active(today=today):
                continue
            grouped.setdefault(exception.owner, []).append(
                exception.to_report_entry()
            )
        return {
            owner: sorted(entries, key=lambda item: item["category"])
            for owner, entries in sorted(grouped.items())
        }


def _parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return date.min
    return datetime.fromisoformat(str(value)).date()


def _today() -> date:
    return datetime.now(timezone.utc).date()
