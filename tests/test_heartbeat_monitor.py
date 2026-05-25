from src.agent.heartbeat import HeartbeatMonitor, RunState


def test_heartbeat_does_not_revive_completed_run():
    monitor = HeartbeatMonitor()
    monitor.start_run("run-1", now=1.0)
    assert monitor.complete_run("run-1", RunState.COMPLETED)

    result = monitor.heartbeat("run-1", now=2.0)

    assert not result.accepted
    assert result.state is RunState.COMPLETED
    assert result.reason == "terminal_state"
    assert monitor.get_state("run-1") is RunState.COMPLETED
    assert not monitor.has_lock("run-1")


def test_heartbeat_retry_preserves_first_terminal_outcome():
    monitor = HeartbeatMonitor()
    monitor.start_run("run-1", now=1.0)
    assert monitor.complete_run("run-1", RunState.COMPLETED)

    assert not monitor.complete_run("run-1", RunState.FAILED)
    retry = monitor.heartbeat("run-1", now=3.0)

    assert retry.state is RunState.COMPLETED
    assert monitor.get_state("run-1") is RunState.COMPLETED
    assert monitor.audit_log[-2]["event"] == "terminal_outcome_preserved"
    assert monitor.audit_log[-1]["event"] == "heartbeat_ignored_terminal"


def test_running_heartbeat_extends_durable_lock():
    monitor = HeartbeatMonitor(stale_after_seconds=10.0)
    monitor.start_run("run-1", now=1.0)

    result = monitor.heartbeat("run-1", now=5.0)

    assert result.accepted
    assert monitor.has_lock("run-1")
    assert monitor.sweep_stale_locks(now=12.0) == []
    assert monitor.sweep_stale_locks(now=16.0) == ["run-1"]


def test_start_run_rejects_terminal_revival_attempt():
    monitor = HeartbeatMonitor()
    monitor.start_run("run-1", now=1.0)
    monitor.complete_run("run-1", RunState.CANCELLED)

    assert not monitor.start_run("run-1", now=2.0)
    assert monitor.get_state("run-1") is RunState.CANCELLED
    assert monitor.audit_log[-1]["event"] == "start_ignored_terminal"


def test_terminal_run_does_not_leave_orphaned_lock_on_late_heartbeat():
    monitor = HeartbeatMonitor()
    monitor.heartbeat("run-1", now=1.0)
    assert monitor.has_lock("run-1")

    monitor.complete_run("run-1", RunState.FAILED)
    late = monitor.heartbeat("run-1", now=2.0)

    assert not late.accepted
    assert late.state is RunState.FAILED
    assert not monitor.has_lock("run-1")
    assert monitor.sweep_stale_locks(now=100.0) == []
