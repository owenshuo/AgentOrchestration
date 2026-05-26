from src.orchestrator.workflow import (
    StepStatus,
    Workflow,
    bind_workflow_parameters,
    merge_workflow_parameters,
)


def test_parameter_merge_preserves_explicit_false_defaults():
    result = merge_workflow_parameters(
        defaults={
            "enabled": False,
            "limit": 0,
            "label": "",
            "retries": 3,
        },
        overrides={"retries": 5},
    )

    assert result.parameters == {
        "enabled": False,
        "limit": 0,
        "label": "",
        "retries": 5,
    }
    assert result.deferred is False
    assert result.audit == {
        "decision": "allow",
        "reason": "merged",
        "default_keys": ["enabled", "label", "limit", "retries"],
        "override_keys": ["retries"],
    }


def test_parameter_merge_allows_override_to_explicit_false():
    result = merge_workflow_parameters(
        defaults={"enabled": True, "mode": "auto"},
        overrides={"enabled": False},
    )

    assert result.parameters == {"enabled": False, "mode": "auto"}
    assert result.applied_overrides == ["enabled"]


def test_bind_parameters_preserves_pending_workflow_lifecycle():
    workflow = Workflow("deploy")

    result = bind_workflow_parameters(
        workflow,
        defaults={"dry_run": False, "region": "us-east"},
        overrides={},
    )

    assert workflow.status == StepStatus.PENDING
    assert workflow.parameters == {"dry_run": False, "region": "us-east"}
    assert result.parameters == workflow.parameters
    assert result.audit["decision"] == "allow"
    assert result.audit["workflow_status"] == "pending"
    assert "dry_run" in result.audit["default_keys"]
    assert "False" not in str(result.audit)
    assert "us-east" not in str(result.audit)


def test_bind_parameters_defers_running_workflow_without_mutation():
    workflow = Workflow("deploy")
    workflow.parameters = {"dry_run": False, "region": "us-east"}
    workflow.status = StepStatus.RUNNING

    result = bind_workflow_parameters(
        workflow,
        defaults={"dry_run": True, "region": "eu-west"},
        overrides={"dry_run": True},
    )

    assert result.deferred is True
    assert result.reason == "workflow_lifecycle_not_mutable"
    assert result.parameters == {"dry_run": False, "region": "us-east"}
    assert workflow.parameters == {"dry_run": False, "region": "us-east"}
    assert workflow.status == StepStatus.RUNNING
    assert result.audit == {
        "decision": "defer",
        "reason": "workflow_lifecycle_not_mutable",
        "workflow_id": workflow.id,
        "workflow_status": "running",
        "existing_parameter_keys": ["dry_run", "region"],
    }
    assert "eu-west" not in str(result.audit)
    assert "False" not in str(result.audit)
