import pytest

from src.orchestrator.workflow import WorkflowManager, WorkflowParameter


def test_workflow_registration_accepts_unique_parameter_aliases():
    manager = WorkflowManager()

    workflow = manager.create_workflow(
        "deploy",
        parameters=[
            WorkflowParameter(name="region", alias="target"),
            WorkflowParameter(name="environment", alias="env"),
        ],
    )

    assert [parameter.binding_key for parameter in workflow.parameters] == [
        "target",
        "env",
    ]
    assert manager.audit_records()[-1]["decision"] == "accepted"


def test_workflow_registration_rejects_duplicate_parameter_aliases():
    manager = WorkflowManager()

    with pytest.raises(ValueError, match="duplicate workflow parameter alias"):
        manager.create_workflow(
            "deploy",
            parameters=[
                WorkflowParameter(name="source_region", alias="region"),
                WorkflowParameter(name="target_region", alias="region"),
            ],
        )

    assert manager.list_workflows() == []
    assert manager.audit_records()[-1] == {
        "action": "workflow_registration",
        "decision": "rejected",
        "reason": "duplicate_parameter_alias",
    }


def test_workflow_registration_rejects_alias_that_collides_with_name():
    manager = WorkflowManager()

    with pytest.raises(ValueError, match="duplicate workflow parameter alias"):
        manager.create_workflow(
            "deploy",
            parameters=[
                WorkflowParameter(name="region"),
                WorkflowParameter(name="target_region", alias="region"),
            ],
        )

    assert manager.list_workflows() == []


def test_workflow_registration_rejects_empty_binding_without_payload():
    manager = WorkflowManager()

    with pytest.raises(ValueError, match="non-empty"):
        manager.create_workflow(
            "deploy",
            parameters=[WorkflowParameter(name="", alias="")],
        )

    audit = manager.audit_records()[-1]
    assert audit["reason"] == "empty_parameter_binding"
    assert "parameters" not in audit
