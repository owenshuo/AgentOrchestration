from src.orchestrator.engine import OrchestrationEngine


def test_reducer_rejects_stale_revision_without_mutating_task():
    engine = OrchestrationEngine()
    task = {"id": "task-1", "state": "queued", "revision": 1, "attempt": 0}

    assert engine._reduce_task_state(
        task,
        "running",
        expected_revision=1,
        expected_attempt=0,
    )
    assert not engine._reduce_task_state(
        task,
        "completed",
        expected_revision=1,
        expected_attempt=0,
    )

    assert task["state"] == "running"
    assert task["revision"] == 2
    assert engine.reducer_errors == [
        {
            "task_id": "task-1",
            "reason": "stale_revision",
            "attempted_state": "completed",
            "current_state": "running",
            "expected_revision": 1,
            "actual_revision": 2,
            "expected_attempt": 0,
            "actual_attempt": 0,
        }
    ]


def test_reducer_rejects_stale_attempt_without_mutating_task():
    engine = OrchestrationEngine()
    task = {"id": "task-2", "state": "queued", "revision": 0, "attempt": 0}

    engine._begin_task_attempt(task)

    assert not engine._reduce_task_state(
        task,
        "running",
        expected_revision=0,
        expected_attempt=0,
    )

    assert task["state"] == "queued"
    assert task["revision"] == 0
    assert task["attempt"] == 1
    assert engine.reducer_errors[0]["reason"] == "stale_attempt"
    assert engine.reducer_errors[0]["expected_attempt"] == 0
    assert engine.reducer_errors[0]["actual_attempt"] == 1


def test_reducer_preserves_terminal_lifecycle_state():
    engine = OrchestrationEngine()
    task = {"id": "task-3", "state": "completed", "revision": 4, "attempt": 2}

    assert not engine._reduce_task_state(
        task,
        "running",
        expected_revision=4,
        expected_attempt=2,
    )

    assert task == {
        "id": "task-3",
        "state": "completed",
        "revision": 4,
        "attempt": 2,
    }
    assert engine.reducer_errors[0]["reason"] == "terminal_state"


def test_reducer_errors_are_bounded_and_sanitized():
    engine = OrchestrationEngine()

    for index in range(105):
        task = {
            "id": f"task-{index}",
            "state": "queued",
            "revision": 2,
            "attempt": 0,
            "payload": {"secret": "do-not-persist"},
        }
        assert not engine._reduce_task_state(
            task,
            "completed",
            expected_revision=1,
            expected_attempt=0,
        )

    errors = engine.reducer_errors
    assert len(errors) == 100
    assert errors[0]["task_id"] == "task-5"
    assert errors[-1]["task_id"] == "task-104"
    assert all("payload" not in error for error in errors)
    assert all("secret" not in str(error) for error in errors)
