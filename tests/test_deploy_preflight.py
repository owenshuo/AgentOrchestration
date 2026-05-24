from datetime import datetime, timedelta, timezone

import pytest

from src.deploy.preflight import (
    BackupStatus,
    MigrationMetadata,
    run_migration_preflight,
)

NOW = datetime(2026, 5, 24, 15, 0, tzinfo=timezone.utc)


def test_non_destructive_migration_declares_metadata_and_skips_backup_gate():
    migration = MigrationMetadata.from_manifest(
        {"name": "add-index", "destructive": False}
    )

    report = run_migration_preflight(migration, None, now=NOW)

    assert report.passed
    assert report.migration_name == "add-index"
    assert not report.destructive
    assert report.reason == "backup gate not required"


def test_destructive_migration_fails_without_backup():
    migration = MigrationMetadata(name="drop-users-column", destructive=True)

    report = run_migration_preflight(migration, None, now=NOW)

    assert not report.passed
    assert report.destructive
    assert report.backup_timestamp is None
    assert not report.restore_verified
    assert report.restore_checked_at is None
    assert report.reason == "missing verified backup"


def test_destructive_migration_fails_when_backup_is_too_old():
    migration = MigrationMetadata(name="rewrite-ledger", destructive=True)
    backup = BackupStatus(
        created_at=NOW - timedelta(hours=25),
        restore_verified=True,
        restore_checked_at=NOW - timedelta(hours=24),
    )

    report = run_migration_preflight(migration, backup, now=NOW)

    assert not report.passed
    assert report.backup_timestamp == backup.created_at
    assert report.restore_verified
    assert report.restore_checked_at == backup.restore_checked_at
    assert report.reason == "backup is too old"


def test_destructive_migration_fails_when_restore_is_not_verified():
    migration = MigrationMetadata(name="delete-legacy-table", destructive=True)
    backup = BackupStatus(
        created_at=NOW - timedelta(hours=2),
        restore_verified=False,
        restore_checked_at=None,
    )

    report = run_migration_preflight(migration, backup, now=NOW)

    assert not report.passed
    assert report.backup_timestamp == backup.created_at
    assert not report.restore_verified
    assert report.restore_checked_at is None
    assert report.reason == "backup restore is not verified"


def test_destructive_migration_passes_with_recent_verified_backup():
    migration = MigrationMetadata(
        name="truncate-audit-shadow",
        destructive=True,
    )
    backup = BackupStatus(
        created_at=NOW - timedelta(minutes=30),
        restore_verified=True,
        restore_checked_at=NOW - timedelta(minutes=20),
    )

    report = run_migration_preflight(migration, backup, now=NOW)

    assert report.passed
    assert report.backup_timestamp == backup.created_at
    assert report.restore_verified
    assert report.restore_checked_at == backup.restore_checked_at
    assert report.reason == "recent verified backup available"
    report_data = report.to_dict()
    assert report_data["backup_timestamp"] == backup.created_at.isoformat()
    assert report_data["restore_checked_at"] == (
        backup.restore_checked_at.isoformat()
    )


def test_irreversible_migration_requires_backup_even_if_not_destructive():
    migration = MigrationMetadata(
        name="hash-personal-identifiers",
        destructive=False,
        irreversible=True,
    )

    report = run_migration_preflight(migration, None, now=NOW)

    assert not report.passed
    assert report.reason == "missing verified backup"


def test_migration_manifest_must_declare_destructive_flag():
    with pytest.raises(ValueError) as error:
        MigrationMetadata.from_manifest({"name": "ambiguous-change"})

    assert str(error.value) == "migration metadata must declare destructive"


def test_migration_manifest_destructive_flag_must_be_boolean():
    with pytest.raises(ValueError) as error:
        MigrationMetadata.from_manifest(
            {"name": "drop-table", "destructive": "yes"}
        )

    assert str(error.value) == "migration destructive metadata must be boolean"
