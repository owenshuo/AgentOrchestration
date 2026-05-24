"""Release preflight checks for database migrations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

DEFAULT_BACKUP_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class MigrationMetadata:
    """Metadata each migration must declare before release."""

    name: str
    destructive: bool
    irreversible: bool = False

    @classmethod
    def from_manifest(cls, manifest: Dict[str, Any]) -> "MigrationMetadata":
        if "destructive" not in manifest:
            raise ValueError("migration metadata must declare destructive")
        if not isinstance(manifest["destructive"], bool):
            raise ValueError("migration destructive metadata must be boolean")
        return cls(
            name=str(manifest.get("name", "unnamed-migration")),
            destructive=manifest["destructive"],
            irreversible=bool(manifest.get("irreversible", False)),
        )

    @property
    def requires_verified_backup(self) -> bool:
        return self.destructive or self.irreversible


@dataclass(frozen=True)
class BackupStatus:
    """Latest backup and restore verification state."""

    created_at: Optional[datetime]
    restore_verified: bool
    restore_checked_at: Optional[datetime] = None


@dataclass(frozen=True)
class PreflightReport:
    """Result returned to deployment tooling before migration execution."""

    migration_name: str
    destructive: bool
    passed: bool
    backup_timestamp: Optional[datetime]
    restore_verified: bool
    restore_checked_at: Optional[datetime]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "migration_name": self.migration_name,
            "destructive": self.destructive,
            "passed": self.passed,
            "backup_timestamp": _isoformat(self.backup_timestamp),
            "restore_verified": self.restore_verified,
            "restore_checked_at": _isoformat(self.restore_checked_at),
            "reason": self.reason,
        }


def run_migration_preflight(
    migration: MigrationMetadata,
    backup: Optional[BackupStatus],
    *,
    now: Optional[datetime] = None,
    max_backup_age: timedelta = DEFAULT_BACKUP_MAX_AGE,
) -> PreflightReport:
    """Fail destructive migrations without a recent verified backup."""
    current_time = _as_utc(now or datetime.now(timezone.utc))

    if not migration.requires_verified_backup:
        return PreflightReport(
            migration_name=migration.name,
            destructive=migration.destructive,
            passed=True,
            backup_timestamp=backup.created_at if backup else None,
            restore_verified=backup.restore_verified if backup else False,
            restore_checked_at=(
                backup.restore_checked_at if backup else None
            ),
            reason="backup gate not required",
        )

    if backup is None or backup.created_at is None:
        return _failed_report(migration, backup, "missing verified backup")

    backup_time = _as_utc(backup.created_at)
    if current_time - backup_time > max_backup_age:
        return _failed_report(migration, backup, "backup is too old")

    if not backup.restore_verified:
        return _failed_report(
            migration, backup, "backup restore is not verified"
        )

    return PreflightReport(
        migration_name=migration.name,
        destructive=migration.destructive,
        passed=True,
        backup_timestamp=backup.created_at,
        restore_verified=True,
        restore_checked_at=backup.restore_checked_at,
        reason="recent verified backup available",
    )


def _failed_report(
    migration: MigrationMetadata,
    backup: Optional[BackupStatus],
    reason: str,
) -> PreflightReport:
    return PreflightReport(
        migration_name=migration.name,
        destructive=migration.destructive,
        passed=False,
        backup_timestamp=backup.created_at if backup else None,
        restore_verified=backup.restore_verified if backup else False,
        restore_checked_at=backup.restore_checked_at if backup else None,
        reason=reason,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _as_utc(value).isoformat()
