import datetime as dt

from scripts.validate_dependency_review_exceptions import (
    render_summary,
    validate_manifest,
)


def test_valid_exception_manifest_records_required_metadata():
    manifest = {
        "exceptions": [
            {
                "id": "GHSA-example",
                "dependency": "pypi:example@1.0.0",
                "owner": "@security-team",
                "reason": "Temporary upstream patch window",
                "expires_on": "2026-06-30",
                "review_url": "https://github.com/org/repo/actions/runs/1",
            }
        ]
    }

    errors = validate_manifest(
        manifest,
        today=dt.date(2026, 5, 23),
    )
    summary = render_summary(manifest)

    assert errors == []
    assert "pypi:example@1.0.0 owned by @security-team" in summary
    assert "expires 2026-06-30" in summary


def test_expired_exception_fails_validation():
    manifest = {
        "exceptions": [
            {
                "id": "GHSA-old",
                "dependency": "npm:old@1.0.0",
                "owner": "@security-team",
                "reason": "Pending migration",
                "expires_on": "2026-01-01",
                "review_url": "https://github.com/org/repo/actions/runs/1",
            }
        ]
    }

    errors = validate_manifest(
        manifest,
        today=dt.date(2026, 5, 23),
    )

    assert errors == ["exceptions[0].expires_on expired on 2026-01-01"]


def test_missing_owner_and_expiration_are_rejected():
    manifest = {
        "exceptions": [
            {
                "id": "GHSA-missing",
                "dependency": "pypi:example@1.0.0",
                "reason": "No owner",
                "review_url": "https://github.com/org/repo/actions/runs/1",
            }
        ]
    }

    errors = validate_manifest(
        manifest,
        today=dt.date(2026, 5, 23),
    )

    assert "exceptions[0] missing required fields: expires_on, owner" in errors
    assert "exceptions[0].owner must be a non-empty string" in errors
    assert "exceptions[0].expires_on must use YYYY-MM-DD" in errors


def test_duplicate_exception_ids_are_rejected():
    manifest = {
        "exceptions": [
            {
                "id": "DUP",
                "dependency": "pypi:a@1",
                "owner": "@security-team",
                "reason": "Temporary",
                "expires_on": "2026-06-01",
                "review_url": "https://github.com/org/repo/actions/runs/1",
            },
            {
                "id": "DUP",
                "dependency": "pypi:b@1",
                "owner": "@security-team",
                "reason": "Temporary",
                "expires_on": "2026-06-01",
                "review_url": "https://github.com/org/repo/actions/runs/2",
            },
        ]
    }

    errors = validate_manifest(
        manifest,
        today=dt.date(2026, 5, 23),
    )

    assert "exceptions[1].id duplicates DUP" in errors
