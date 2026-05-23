from datetime import date

import pytest

from src.data.retention_exceptions import (
    RetentionException,
    RetentionExceptionRegistry,
    RetentionExceptionValidationError,
)

TODAY = date(2026, 5, 23)


def test_retention_exception_requires_owner_reason_expiration_and_review():
    exception = RetentionException(
        category="validation-payloads",
        owner="",
        reason="investigation hold",
        expires_at=date(2026, 6, 1),
        review_at=date(2026, 5, 30),
    )

    with pytest.raises(
        RetentionExceptionValidationError,
        match="owner",
    ):
        exception.validate(today=TODAY)


def test_expired_exception_fails_governance_validation():
    registry = RetentionExceptionRegistry(
        [
            RetentionException(
                category="artifact-cache",
                owner="data-governance",
                reason="legal hold",
                expires_at=date(2026, 5, 22),
                review_at=date(2026, 5, 20),
            )
        ]
    )

    with pytest.raises(
        RetentionExceptionValidationError,
        match="expired on 2026-05-22",
    ):
        registry.validate(today=TODAY)


def test_review_date_must_not_follow_expiration():
    exception = RetentionException(
        category="debug-exports",
        owner="security",
        reason="incident review",
        expires_at=date(2026, 6, 1),
        review_at=date(2026, 6, 2),
    )

    with pytest.raises(
        RetentionExceptionValidationError,
        match="review date after expiration",
    ):
        exception.validate(today=TODAY)


def test_active_exception_report_groups_entries_by_owner():
    registry = RetentionExceptionRegistry()
    registry.add(
        RetentionException(
            category="validation-payloads",
            owner="data-governance",
            reason="customer dispute",
            expires_at=date(2026, 6, 1),
            review_at=date(2026, 5, 30),
        ),
        today=TODAY,
    )
    registry.add(
        RetentionException(
            category="artifact-cache",
            owner="security",
            reason="incident review",
            expires_at=date(2026, 6, 15),
            review_at=date(2026, 6, 1),
        ),
        today=TODAY,
    )
    registry.add(
        RetentionException(
            category="failed-validation",
            owner="data-governance",
            reason="audit sampling",
            expires_at=date(2026, 6, 20),
            review_at=date(2026, 6, 10),
        ),
        today=TODAY,
    )

    report = registry.active_by_owner(today=TODAY)

    assert set(report) == {"data-governance", "security"}
    assert [
        entry["category"] for entry in report["data-governance"]
    ] == ["failed-validation", "validation-payloads"]
    assert report["security"] == [
        {
            "category": "artifact-cache",
            "reason": "incident review",
            "expires_at": "2026-06-15",
            "review_at": "2026-06-01",
        }
    ]


def test_exception_can_be_loaded_from_governance_metadata_dict():
    exception = RetentionException.from_dict(
        {
            "category": "exports",
            "owner": "privacy",
            "reason": "subject access request",
            "expires_at": "2026-07-01",
            "review_at": "2026-06-15",
        }
    )

    exception.validate(today=TODAY)
    assert exception.owner == "privacy"
    assert exception.expires_at == date(2026, 7, 1)
