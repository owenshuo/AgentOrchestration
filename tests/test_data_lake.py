import pytest

from src.common.data_lake import (
    DataClassificationRegistry,
    DataLakeIngestionPipeline,
    DataLakePolicyError,
    IngestionManifest,
)


def test_data_lake_write_requires_governance_manifest_fields():
    registry = DataClassificationRegistry()
    registry.register_destination("analytics.ops", {"operational"})
    pipeline = DataLakeIngestionPipeline(registry)

    with pytest.raises(DataLakePolicyError, match="purpose is required"):
        pipeline.ingest(
            {"task_id": "task-1"},
            IngestionManifest(
                purpose="",
                data_class="operational",
                owner="security",
                destination="analytics.ops",
            ),
        )

    assert pipeline.audit_records[-1]["decision"] == "rejected"
    assert pipeline.audit_records[-1]["reason"] == "missing_purpose"


def test_ingestion_rejects_destination_without_allowed_data_class():
    registry = DataClassificationRegistry()
    registry.register_destination("analytics.aggregate", {"aggregate"})
    pipeline = DataLakeIngestionPipeline(registry)

    with pytest.raises(DataLakePolicyError, match="does not allow"):
        pipeline.ingest(
            {"task_id": "task-1", "agent_id": "agent-1"},
            IngestionManifest(
                purpose="incident-investigation",
                data_class="operational",
                owner="security",
                destination="analytics.aggregate",
            ),
        )

    assert pipeline.audit_records[-1]["decision"] == "rejected"
    assert pipeline.audit_records[-1]["reason"] == "destination_policy_denied"
    assert "task-1" not in str(pipeline.audit_records[-1])


def test_ingestion_accepts_approved_destination_and_records_purpose():
    registry = DataClassificationRegistry()
    registry.register_destination("lake.security", {"operational"})
    pipeline = DataLakeIngestionPipeline(registry)

    write = pipeline.ingest(
        {"task_id": "task-1"},
        IngestionManifest(
            purpose="incident-investigation",
            data_class="operational",
            owner="security",
            destination="lake.security",
            metadata={"retention": "30d"},
        ),
    )

    assert write["purpose"] == "incident-investigation"
    assert write["owner"] == "security"
    assert write["data_class"] == "operational"
    assert write["destination"] == "lake.security"
    assert pipeline.audit_records[-1]["decision"] == "accepted"
    assert pipeline.audit_records[-1]["write_id"] == write["write_id"]


def test_audit_report_lists_writes_by_purpose_and_owner():
    registry = DataClassificationRegistry()
    registry.register_destination("lake.security", {"operational"})
    registry.register_destination("lake.finance", {"financial"})
    pipeline = DataLakeIngestionPipeline(registry)

    pipeline.ingest(
        {"task_id": "task-1"},
        IngestionManifest(
            purpose="incident-investigation",
            data_class="operational",
            owner="security",
            destination="lake.security",
        ),
    )
    pipeline.ingest(
        {"expense_id": "expense-1"},
        IngestionManifest(
            purpose="audit-review",
            data_class="financial",
            owner="finance",
            destination="lake.finance",
        ),
    )
    pipeline.ingest(
        {"task_id": "task-2"},
        IngestionManifest(
            purpose="incident-investigation",
            data_class="operational",
            owner="security",
            destination="lake.security",
        ),
    )

    report = sorted(
        pipeline.audit_report(),
        key=lambda row: (row["owner"], row["purpose"]),
    )

    assert report == [
        {
            "purpose": "audit-review",
            "owner": "finance",
            "write_count": 1,
            "destinations": ["lake.finance"],
            "data_classes": ["financial"],
        },
        {
            "purpose": "incident-investigation",
            "owner": "security",
            "write_count": 2,
            "destinations": ["lake.security"],
            "data_classes": ["operational"],
        },
    ]
