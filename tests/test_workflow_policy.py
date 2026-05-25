import pytest

from src.orchestrator.workflow import (
    StepStatus,
    Workflow,
    WorkflowManager,
    WorkflowPolicyInjector,
    WorkflowStep,
    WorkflowValidationError,
)


def handler():
    return "ok"


def test_register_workflow_injects_and_validates_guard_nodes():
    manager = WorkflowManager()
    workflow = Workflow("guarded")
    step = WorkflowStep("run_agent", handler)
    workflow.add_step(step)

    manager.register_workflow(workflow)

    assert manager.get_workflow(workflow.id) is workflow
    assert [item.is_guard for item in workflow.steps] == [True, False]
    assert workflow.steps[0].protects_step_id == step.id
    assert manager.audit_records[-1] == {
        "workflow_id": workflow.id,
        "event": "policy_graph_accepted",
        "reason": "automatic guard nodes validated",
    }


def test_policy_injection_rejects_stale_lifecycle_transition():
    manager = WorkflowManager()
    workflow = Workflow("stale")
    step = WorkflowStep("run_agent", handler)
    step.status = StepStatus.RUNNING
    workflow.add_step(step)

    with pytest.raises(WorkflowValidationError, match="stale workflow step"):
        manager.register_workflow(workflow)

    assert manager.get_workflow(workflow.id) is None
    assert manager.audit_records[-1]["event"] == "policy_graph_rejected"
    assert step.status is StepStatus.RUNNING


def test_policy_validation_rejects_duplicate_step_ids_after_injection():
    manager = WorkflowManager()
    workflow = Workflow("duplicate")
    workflow.add_step(WorkflowStep("first", handler, step_id="same-id"))
    workflow.add_step(WorkflowStep("second", handler, step_id="same-id"))

    with pytest.raises(WorkflowValidationError, match="duplicate"):
        manager.register_workflow(workflow)

    assert manager.get_workflow(workflow.id) is None
    assert "same-id" in manager.audit_records[-1]["reason"]


def test_policy_validation_rejects_missing_automatic_guard_node():
    workflow = Workflow("missing-guard")
    step = WorkflowStep("run_agent", handler)
    workflow.add_step(step)

    with pytest.raises(WorkflowValidationError, match="guard missing"):
        WorkflowPolicyInjector().validate(workflow)


def test_rejected_update_preserves_previous_workflow_state():
    manager = WorkflowManager()
    current = Workflow("current")
    current.id = "workflow-id"
    current.add_step(WorkflowStep("current-step", handler))
    manager.register_workflow(current)

    replacement = Workflow("replacement")
    replacement.id = "workflow-id"
    replacement_step = WorkflowStep("replacement-step", handler)
    replacement_step.status = StepStatus.RUNNING
    replacement.add_step(replacement_step)

    with pytest.raises(WorkflowValidationError):
        manager.register_workflow(replacement)

    assert manager.get_workflow("workflow-id") is current
    assert current.status is StepStatus.PENDING
