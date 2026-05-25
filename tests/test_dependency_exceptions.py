from datetime import date
import json

import pytest

from scripts.validate_dependency_exceptions import (
    ValidationError,
    validate,
    write_summary,
)


def write_manifest(tmp_path, exceptions):
    path = tmp_path / "dependency-review-exceptions.json"
    path.write_text(json.dumps({"exceptions": exceptions}), encoding="utf-8")
    return path


def write_overrides(tmp_path, overrides):
    path = tmp_path / "dependency-review-overrides.json"
    path.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
    return path


def exception(**overrides):
    entry = {
        "id": "pip-django-ghsa-1234",
        "owner": "@security",
        "reason": "Temporary upstream remediation window",
        "expires": "2099-01-01",
        "dependency": {
            "ecosystem": "pip",
            "name": "django",
            "version": "4.2.0",
        },
    }
    entry.update(overrides)
    return entry


def test_empty_manifest_is_valid(tmp_path):
    manifest = write_manifest(tmp_path, [])

    assert validate(manifest, None, date(2026, 5, 25)) == []


def test_active_exception_requires_owner(tmp_path):
    entry = exception(owner="")
    manifest = write_manifest(tmp_path, [entry])

    with pytest.raises(ValidationError, match="owner"):
        validate(manifest, None, date(2026, 5, 25))


def test_active_exception_requires_expiration(tmp_path):
    entry = exception(expires="")
    manifest = write_manifest(tmp_path, [entry])

    with pytest.raises(ValidationError, match="expires"):
        validate(manifest, None, date(2026, 5, 25))


def test_expired_exception_fails_until_removed_or_renewed(tmp_path):
    entry = exception(expires="2026-05-24")
    manifest = write_manifest(tmp_path, [entry])

    with pytest.raises(ValidationError, match="expired"):
        validate(manifest, None, date(2026, 5, 25))


def test_duplicate_exception_ids_fail(tmp_path):
    manifest = write_manifest(tmp_path, [exception(), exception()])

    with pytest.raises(ValidationError, match="duplicate"):
        validate(manifest, None, date(2026, 5, 25))


def test_dependency_coordinates_are_required(tmp_path):
    entry = exception(dependency={"ecosystem": "pip", "name": "django"})
    manifest = write_manifest(tmp_path, [entry])

    with pytest.raises(ValidationError, match="version"):
        validate(manifest, None, date(2026, 5, 25))


def test_override_requires_matching_manifest_entry_by_id(tmp_path):
    manifest = write_manifest(tmp_path, [exception()])
    overrides = write_overrides(
        tmp_path,
        [{"id": "npm-react-ghsa-9999", "dependency": {}}],
    )

    with pytest.raises(ValidationError, match="missing tracked"):
        validate(manifest, overrides, date(2026, 5, 25))


def test_override_matches_manifest_entry_by_dependency_coordinates(tmp_path):
    manifest = write_manifest(tmp_path, [exception()])
    overrides = write_overrides(
        tmp_path,
        [
            {
                "dependency": {
                    "ecosystem": "pip",
                    "name": "django",
                    "version": "4.2.0",
                }
            }
        ],
    )

    assert validate(manifest, overrides, date(2026, 5, 25))


def test_summary_links_active_exceptions_to_manifest_record(tmp_path):
    manifest = write_manifest(tmp_path, [exception()])
    summary = tmp_path / "summary.md"

    write_summary(summary, validate(manifest, None, date(2026, 5, 25)))

    content = summary.read_text(encoding="utf-8")
    assert "pip-django-ghsa-1234" in content
    assert "[manifest](" in content
