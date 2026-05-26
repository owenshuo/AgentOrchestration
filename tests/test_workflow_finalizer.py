from src.orchestrator.workflow import (
    StepStatus,
    Workflow,
    WorkflowManager,
    WorkflowStep,
    WorkflowFinalizationToken,
    WorkflowFinalizer,
)


def _token(workflow, attempt=1):
    return WorkflowFinalizationToken(
        workflow_id=workflow.id,
        attempt=attempt,
        revision=workflow.revision,
    )


def test_duplicate_terminal_event_is_idempotent():
    workflow = Workflow("finalize once")
    finalizer = WorkflowFinalizer()
    token = _token(workflow)

    assert finalizer.finalize(workflow, token, StepStatus.COMPLETED) is True
    revision = workflow.revision

    duplicate = WorkflowFinalizationToken(
        workflow_id=workflow.id,
        attempt=token.attempt,
        revision=revision,
    )
    assert finalizer.finalize(
        workflow,
        duplicate,
        StepStatus.COMPLETED,
    ) is True

    assert workflow.status == StepStatus.COMPLETED
    assert workflow.revision == revision
    assert (
        finalizer.audit_records[-1]["reason"]
        == "duplicate_terminal_event"
    )


def test_manager_finalizes_workflow_once():
    manager = WorkflowManager()
    workflow = manager.create_workflow("execute")
    workflow.add_step(WorkflowStep("step", lambda: "ok"))

    assert manager.execute_workflow(workflow.id) is True
    revision = workflow.revision
    assert manager.execute_workflow(workflow.id) is True

    assert workflow.status == StepStatus.COMPLETED
    assert workflow.revision == revision
    assert len(manager.finalizer.audit_records) == 1


def test_conflicting_terminal_event_is_rejected_after_finalization():
    workflow = Workflow("conflict")
    finalizer = WorkflowFinalizer()

    assert finalizer.finalize(
        workflow,
        _token(workflow),
        StepStatus.COMPLETED,
    ) is True
    conflict = WorkflowFinalizationToken(
        workflow_id=workflow.id,
        attempt=2,
        revision=workflow.revision,
    )

    assert finalizer.finalize(workflow, conflict, StepStatus.FAILED) is False

    assert workflow.status == StepStatus.COMPLETED
    assert finalizer.audit_records[-1]["decision"] == "rejected"
    assert finalizer.audit_records[-1]["reason"] == "terminal_conflict"


def test_stale_finalization_revision_is_rejected():
    workflow = Workflow("stale")
    finalizer = WorkflowFinalizer()
    token = _token(workflow)
    workflow.revision += 1

    assert finalizer.finalize(workflow, token, StepStatus.COMPLETED) is False

    assert workflow.status == StepStatus.PENDING
    assert finalizer.audit_records[-1]["reason"] == "stale_revision"


def test_non_terminal_finalization_is_rejected():
    workflow = Workflow("non terminal")
    finalizer = WorkflowFinalizer()

    assert finalizer.finalize(
        workflow,
        _token(workflow),
        StepStatus.RUNNING,
    ) is False

    assert workflow.status == StepStatus.PENDING
    assert finalizer.audit_records[-1]["reason"] == "non_terminal_status"


def test_finalization_audit_excludes_payloads_and_results():
    workflow = Workflow("audit")
    finalizer = WorkflowFinalizer()

    finalizer.finalize(workflow, _token(workflow), StepStatus.FAILED)

    audit_text = repr(finalizer.audit_records)
    assert "payload" not in audit_text
    assert "result" not in audit_text
