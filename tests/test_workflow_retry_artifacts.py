from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def test_retry_defers_cleanup_for_required_artifacts():
    manager = WorkflowManager()
    workflow = manager.create_workflow("retry-artifacts")
    calls = []

    def flaky_handler():
        calls.append("attempt")
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    step = WorkflowStep(
        "use-artifact",
        flaky_handler,
        retries=1,
        cleanup_artifacts=["artifact://run/input.json"],
        retry_dependency_artifacts=["artifact://run/input.json"],
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id)
    assert calls == ["attempt", "attempt"]
    assert step.status is StepStatus.COMPLETED
    assert step.result == {"ok": True}
    assert workflow.pending_cleanup == {}
    assert workflow.audit_records == [
        {
            "event": "artifact_cleanup_deferred",
            "workflow_id": workflow.id,
            "step_id": step.id,
            "step_name": "use-artifact",
            "artifacts": ["artifact://run/input.json"],
            "attempt": 1,
            "remaining_retries": 1,
            "reason": "retry_dependency_data",
        },
        {
            "event": "artifact_cleanup_released",
            "workflow_id": workflow.id,
            "step_id": step.id,
            "step_name": "use-artifact",
            "artifacts": ["artifact://run/input.json"],
            "reason": "retry_completed",
        },
    ]


def test_retry_without_dependency_overlap_does_not_defer_cleanup():
    manager = WorkflowManager()
    workflow = manager.create_workflow("retry-artifacts")

    def failing_handler():
        raise RuntimeError("still failing")

    step = WorkflowStep(
        "cleanup-safe-artifact",
        failing_handler,
        retries=1,
        cleanup_artifacts=["artifact://run/temp.log"],
        retry_dependency_artifacts=["artifact://run/input.json"],
    )
    workflow.add_step(step)

    assert not manager.execute_workflow(workflow.id)
    assert step.status is StepStatus.FAILED
    assert step.attempts == 2
    assert workflow.pending_cleanup == {}
    assert workflow.audit_records == []
