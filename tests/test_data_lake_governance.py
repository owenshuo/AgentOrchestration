import pytest

from src.data_lake import DataLakeGovernance, PurposePolicyError


def test_data_lake_write_requires_manifest_governance_fields():
    governance = DataLakeGovernance()
    governance.register_destination(
        "ops_events",
        allowed_data_classes=["operational_task_event"],
    )

    with pytest.raises(PurposePolicyError, match="missing required fields"):
        governance.write(
            records=[{"task_id": "task-1"}],
            manifest_payload={
                "purpose": "scheduler_observability",
                "data_class": "operational_task_event",
                "destination": "ops_events",
            },
        )


def test_data_lake_write_rejects_unapproved_destination_policy():
    governance = DataLakeGovernance()
    governance.register_destination(
        "analytics_events",
        allowed_data_classes=["aggregate_metric"],
        approved_purposes=["analytics"],
    )

    with pytest.raises(PurposePolicyError, match="does not allow"):
        governance.write(
            records=[{"task_id": "task-1", "payload": "private"}],
            manifest_payload={
                "purpose": "scheduler_observability",
                "data_class": "operational_task_event",
                "owner": "scheduler",
                "destination": "analytics_events",
            },
        )


def test_data_lake_write_accepts_approved_purpose_and_class():
    governance = DataLakeGovernance()
    governance.register_destination(
        "ops_events",
        allowed_data_classes=["operational_task_event"],
        approved_purposes=["scheduler_observability"],
    )

    write = governance.write(
        records=[
            {"task_id": "task-1", "state": "queued"},
            {"task_id": "task-2", "state": "running"},
        ],
        manifest_payload={
            "purpose": "scheduler_observability",
            "data_class": "operational_task_event",
            "owner": "scheduler",
            "destination": "ops_events",
        },
    )

    assert write.record_count == 2
    assert write.manifest.owner == "scheduler"


def test_audit_report_lists_writes_by_purpose_and_owner():
    governance = DataLakeGovernance()
    governance.register_destination(
        "ops_events",
        allowed_data_classes=["operational_task_event", "aggregate_metric"],
        approved_purposes=["scheduler_observability", "capacity_planning"],
    )
    governance.write(
        records=[{"task_id": "task-1"}],
        manifest_payload={
            "purpose": "scheduler_observability",
            "data_class": "operational_task_event",
            "owner": "scheduler",
            "destination": "ops_events",
        },
    )
    governance.write(
        records=[{"queue": "default"}, {"queue": "priority"}],
        manifest_payload={
            "purpose": "capacity_planning",
            "data_class": "aggregate_metric",
            "owner": "platform",
            "destination": "ops_events",
        },
    )

    report = governance.audit_report()

    assert report.by_purpose == {
        "capacity_planning": 2,
        "scheduler_observability": 1,
    }
    assert report.by_owner == {"platform": 2, "scheduler": 1}
    assert report.writes == [
        {
            "purpose": "scheduler_observability",
            "data_class": "operational_task_event",
            "owner": "scheduler",
            "destination": "ops_events",
            "record_count": 1,
        },
        {
            "purpose": "capacity_planning",
            "data_class": "aggregate_metric",
            "owner": "platform",
            "destination": "ops_events",
            "record_count": 2,
        },
    ]
