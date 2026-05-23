from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def test_partial_rollback_blocks_downstream_steps_without_running_them():
    manager = WorkflowManager()
    workflow = manager.create_workflow("rollback")
    events = []

    def first_handler():
        events.append("first")
        return {"private": "result"}

    def broken_compensation(result):
        events.append("compensate-first")
        raise RuntimeError("rollback store unavailable")

    def failing_handler():
        events.append("second")
        raise RuntimeError("second failed")

    def downstream_handler():
        events.append("downstream")

    first = WorkflowStep(
        "first", first_handler, compensation=broken_compensation
    )
    second = WorkflowStep("second", failing_handler)
    downstream = WorkflowStep("downstream", downstream_handler)
    workflow.add_step(first).add_step(second).add_step(downstream)

    assert manager.execute_workflow(workflow.id) is False

    assert events == ["first", "second", "compensate-first"]
    assert workflow.status == StepStatus.ROLLBACK_FAILED
    assert first.status == StepStatus.ROLLBACK_FAILED
    assert second.status == StepStatus.FAILED
    assert downstream.status == StepStatus.BLOCKED
    assert workflow.audit_log[-1]["event"] == "downstream_blocked"
    assert workflow.audit_log[-1]["reason"] == "partial_rollback"
    assert "private" not in workflow.audit_log[-1]


def test_successful_compensation_still_stops_workflow_cleanly():
    manager = WorkflowManager()
    workflow = manager.create_workflow("rollback")
    events = []

    def first_handler():
        events.append("first")
        return "ok"

    def compensation(result):
        events.append(f"compensate-{result}")

    def failing_handler():
        events.append("second")
        raise RuntimeError("second failed")

    first = WorkflowStep("first", first_handler, compensation=compensation)
    second = WorkflowStep("second", failing_handler)
    workflow.add_step(first).add_step(second)

    assert manager.execute_workflow(workflow.id) is False

    assert events == ["first", "second", "compensate-ok"]
    assert workflow.status == StepStatus.FAILED
    assert first.status == StepStatus.COMPENSATED
    assert second.status == StepStatus.FAILED
    assert workflow.audit_log[-1]["event"] == "compensation_completed"


def test_audit_log_is_bounded_for_repeated_compensation_events():
    manager = WorkflowManager()
    workflow = manager.create_workflow("bounded")
    step = WorkflowStep("step", lambda: None)

    for index in range(105):
        manager._record_audit(workflow, step, "event", f"reason-{index}")

    assert len(workflow.audit_log) == 100
    assert workflow.audit_log[0]["reason"] == "reason-5"
    assert workflow.audit_log[-1]["reason"] == "reason-104"
