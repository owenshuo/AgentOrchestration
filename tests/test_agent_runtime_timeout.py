import os
import sys
import time

from src.agent.runtime import AgentRuntime, RuntimeState


def _process_is_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _sleeping_agent_command():
    return [
        sys.executable,
        "-c",
        (
            "import subprocess, sys, time; "
            "child = subprocess.Popen(["
            "sys.executable, '-c', 'import time; time.sleep(30)'"
            "]); "
            "print(child.pid, flush=True); "
            "time.sleep(30)"
        ),
    ]


def test_timeout_cancels_process_group_with_one_terminal_outcome():
    runtime = AgentRuntime()

    assert runtime.start("agent-timeout", _sleeping_agent_command())
    proc = runtime._processes["agent-timeout"]
    child_pid = int(proc.stdout.readline().decode().strip())

    outcome = runtime.cancel_after_timeout(
        "agent-timeout",
        "run-timeout",
        timeout=1,
        grace_period=1,
    )
    second_outcome = runtime.cancel_after_timeout(
        "agent-timeout",
        "run-timeout",
        timeout=1,
        grace_period=1,
    )

    assert outcome is second_outcome
    assert outcome.state is RuntimeState.TIMED_OUT
    assert runtime.get_state("agent-timeout") is RuntimeState.TIMED_OUT
    assert not runtime.is_running("agent-timeout")
    assert proc.poll() is not None

    deadline = time.time() + 3
    while _process_is_alive(child_pid) and time.time() < deadline:
        time.sleep(0.05)
    assert not _process_is_alive(child_pid)

    terminal_records = [
        record
        for record in runtime.audit_records()
        if record["event"] == "timeout_terminal_recorded"
    ]
    assert len(terminal_records) == 1


def test_stop_terminates_process_group_children():
    runtime = AgentRuntime()

    assert runtime.start("agent-stop", _sleeping_agent_command())
    proc = runtime._processes["agent-stop"]
    child_pid = int(proc.stdout.readline().decode().strip())

    assert runtime.stop("agent-stop", timeout=1)
    assert runtime.get_state("agent-stop") is RuntimeState.STOPPED
    assert proc.poll() is not None

    deadline = time.time() + 3
    while _process_is_alive(child_pid) and time.time() < deadline:
        time.sleep(0.05)
    assert not _process_is_alive(child_pid)
