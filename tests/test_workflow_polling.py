from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def test_deleted_workflow_rejects_stale_poll_commit_without_state_change():
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup race")
    token = manager.poll_coordinator.begin_poll(workflow.id)

    assert token is not None
    assert manager.delete_workflow(workflow.id) is True

    assert manager.poll_coordinator.commit_poll(
        token,
        StepStatus.COMPLETED,
    ) is False
    assert manager.get_workflow(workflow.id) is None

    rejected = manager.poll_coordinator.audit_records[-1]
    assert rejected["decision"] == "rejected"
    assert rejected["reason"] == "workflow_deleted"
    assert rejected["workflow_id"] == workflow.id
    assert "payload" not in rejected
    assert "result" not in rejected


def test_poll_after_workflow_deletion_is_not_started():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deleted before poll")

    manager.delete_workflow(workflow.id)

    assert manager.poll_coordinator.begin_poll(workflow.id) is None

    rejected = manager.poll_coordinator.audit_records[-1]
    assert rejected["decision"] == "rejected"
    assert rejected["reason"] == "workflow_deleted"
    assert rejected["revision"] == 1


def test_newer_poll_attempt_rejects_older_commit():
    manager = WorkflowManager()
    workflow = manager.create_workflow("attempt race")
    first = manager.poll_coordinator.begin_poll(workflow.id)
    second = manager.poll_coordinator.begin_poll(workflow.id)

    assert first is not None
    assert second is not None
    assert manager.poll_coordinator.commit_poll(
        first,
        StepStatus.COMPLETED,
    ) is False

    assert manager.get_workflow(workflow.id).status == StepStatus.PENDING
    rejected = manager.poll_coordinator.audit_records[-1]
    assert rejected["reason"] == "stale_attempt"
    assert rejected["current_attempt"] == second.attempt


def test_active_poll_commit_advances_revision_once():
    manager = WorkflowManager()
    workflow = manager.create_workflow("active poll")
    token = manager.poll_coordinator.begin_poll(workflow.id)

    assert token is not None
    assert manager.poll_coordinator.commit_poll(
        token,
        StepStatus.RUNNING,
    ) is True

    current = manager.get_workflow(workflow.id)
    assert current.status == StepStatus.RUNNING
    assert current.revision == token.revision + 1
    assert manager.poll_coordinator.audit_records[-1]["reason"] == (
        "poll_committed"
    )


def test_execute_workflow_stops_after_deletion_during_step_poll():
    manager = WorkflowManager()
    workflow = manager.create_workflow("delete during execution")
    calls = []

    def delete_workflow():
        calls.append("delete")
        assert manager.delete_workflow(workflow.id) is True

    def stale_step():
        calls.append("stale")

    first = WorkflowStep("delete", delete_workflow)
    second = WorkflowStep("stale", stale_step)
    workflow.add_step(first).add_step(second)

    assert manager.execute_workflow(workflow.id) is False

    assert calls == ["delete"]
    assert manager.get_workflow(workflow.id) is None
    assert first.status == StepStatus.COMPLETED
    assert second.status == StepStatus.PENDING
    rejected = manager.poll_coordinator.audit_records[-1]
    assert rejected["decision"] == "rejected"
    assert rejected["reason"] == "workflow_deleted"
    assert rejected["workflow_id"] == workflow.id
    assert "payload" not in rejected
    assert "result" not in rejected
