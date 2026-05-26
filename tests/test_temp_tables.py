import pytest

from src.common.temp_tables import TemporaryTableError, TemporaryTableRegistry


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def test_helper_tables_include_retention_labels():
    clock = Clock()
    registry = TemporaryTableRegistry(clock)

    table = registry.create_helper_table(
        "tmp_reconcile_1",
        owner="reconciliation",
        purpose="daily-batch",
        ttl_seconds=60,
        row_count=3,
    )

    assert table.retention_labels() == {
        "owner": "reconciliation",
        "purpose": "daily-batch",
        "expires_at": 160.0,
        "temporary": True,
    }


def test_report_distinguishes_active_and_expired_temporary_tables():
    clock = Clock()
    registry = TemporaryTableRegistry(clock)
    active = registry.create_helper_table(
        "tmp_active",
        owner="reporting",
        purpose="dashboard-refresh",
        ttl_seconds=60,
    )
    expired = registry.create_helper_table(
        "tmp_expired",
        owner="reporting",
        purpose="old-refresh",
        ttl_seconds=10,
    )

    clock.now = 115.0
    report = registry.report()

    assert [row["table_id"] for row in report["active_temporary_tables"]] == [
        active.table_id,
    ]
    assert [row["table_id"] for row in report["expired_temporary_tables"]] == [
        expired.table_id,
    ]


def test_cleanup_removes_expired_helper_tables_after_safety_check():
    clock = Clock()
    registry = TemporaryTableRegistry(clock)
    keep = registry.create_helper_table(
        "tmp_keep",
        owner="reporting",
        purpose="active",
        ttl_seconds=60,
    )
    remove = registry.create_helper_table(
        "tmp_remove",
        owner="reporting",
        purpose="expired",
        ttl_seconds=10,
    )

    clock.now = 120.0
    removed = registry.cleanup_expired(
        lambda table: table.owner == "reporting"
    )

    assert removed == [remove.table_id]
    report = registry.report()
    assert [row["table_id"] for row in report["active_temporary_tables"]] == [
        keep.table_id,
    ]
    assert report["expired_temporary_tables"] == []
    assert registry.audit_records[-1]["decision"] == "removed"


def test_cleanup_skips_expired_table_when_safety_check_fails():
    clock = Clock()
    registry = TemporaryTableRegistry(clock)
    table = registry.create_helper_table(
        "tmp_review",
        owner="finance",
        purpose="audit",
        ttl_seconds=5,
    )

    clock.now = 120.0
    assert registry.cleanup_expired(lambda _table: False) == []

    report = registry.report()
    assert report["expired_temporary_tables"][0]["table_id"] == table.table_id
    assert registry.audit_records[-1]["reason"] == "safety_check_failed"


def test_temporary_table_metadata_is_required():
    registry = TemporaryTableRegistry()

    with pytest.raises(TemporaryTableError, match="owner is required"):
        registry.create_helper_table(
            "tmp_missing_owner",
            owner="",
            purpose="batch",
            ttl_seconds=60,
        )


def test_audit_records_do_not_include_table_rows_or_payloads():
    registry = TemporaryTableRegistry()

    registry.create_helper_table(
        "tmp_sensitive",
        owner="security",
        purpose="investigation",
        ttl_seconds=60,
        row_count=10,
    )

    audit_text = repr(registry.audit_records)
    assert "payload" not in audit_text
    assert "rows" not in audit_text
