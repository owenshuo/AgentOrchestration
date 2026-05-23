import pytest

from src.agent.sandbox import AgentSandbox, ResourceLimits


def test_apply_limits_rejects_unsupported_disk_limit(monkeypatch):
    sandbox = AgentSandbox()
    setrlimit_calls = []

    monkeypatch.setattr(
        "src.agent.sandbox.resource.setrlimit",
        setrlimit_calls.append,
    )

    with pytest.raises(
        NotImplementedError,
        match="disk_mb is not enforced",
    ):
        sandbox.apply_limits("agent-1", ResourceLimits(disk_mb=100))

    assert setrlimit_calls == []


def test_apply_limits_allows_cpu_and_memory_without_disk_limit(monkeypatch):
    sandbox = AgentSandbox()
    calls = []

    def fake_setrlimit(resource_name, limits):
        calls.append((resource_name, limits))

    monkeypatch.setattr(
        "src.agent.sandbox.resource.setrlimit",
        fake_setrlimit,
    )

    sandbox.apply_limits("agent-1", ResourceLimits(cpu_time=5, memory_mb=32))

    assert calls == [
        (sandbox_module_resource().RLIMIT_CPU, (5, 5)),
        (
            sandbox_module_resource().RLIMIT_AS,
            (32 * 1024 * 1024, 32 * 1024 * 1024),
        ),
    ]


def sandbox_module_resource():
    from src.agent import sandbox as sandbox_module

    return sandbox_module.resource
