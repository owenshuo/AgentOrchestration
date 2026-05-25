import pytest

from src.agent.sandbox import (
    AgentSandbox,
    ResourceLimits,
    UnsupportedSandboxLimitError,
)


def test_resource_limits_do_not_advertise_default_disk_quota():
    limits = ResourceLimits()

    assert limits.disk_mb is None


def test_apply_limits_rejects_explicit_disk_limit():
    sandbox = AgentSandbox()

    with pytest.raises(
        UnsupportedSandboxLimitError,
        match="disk_mb is not enforced",
    ):
        sandbox.apply_limits("agent-a", ResourceLimits(disk_mb=100))


def test_apply_limits_allows_cpu_and_memory_without_disk(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.agent.sandbox.resource.setrlimit",
        lambda limit, values: calls.append((limit, values)),
    )

    sandbox = AgentSandbox()
    sandbox.apply_limits("agent-a", ResourceLimits(cpu_time=12, memory_mb=2))

    assert calls == [
        (0, (12, 12)),
        (9, (2 * 1024 * 1024, 2 * 1024 * 1024)),
    ]
