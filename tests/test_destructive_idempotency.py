import asyncio

import pytest
from fastapi import HTTPException

from src.agent import AgentRegistry
from src.api import routes
from src.api.idempotency import (
    DestructiveActionIdempotencyStore,
    IdempotencyConflictError,
)
from src.sdk.client import OrchestratorClient


def setup_function():
    routes.registry = AgentRegistry()
    routes.destructive_idempotency = DestructiveActionIdempotencyStore()


def test_delete_agent_replays_same_key_after_first_delete():
    agent_id = routes.registry.register("cleanup-agent", "worker.cleanup")

    first = asyncio.run(
        routes.delete_agent(agent_id, idempotency_key="double-click-1")
    )
    replay = asyncio.run(
        routes.delete_agent(agent_id, idempotency_key="double-click-1")
    )

    assert first == {"status": "deleted", "agent_id": agent_id}
    assert replay == first
    assert routes.registry.get(agent_id) is None
    assert routes.destructive_idempotency.audit_report()[-1]["action"] == (
        "replayed"
    )


def test_delete_agent_without_key_still_returns_404_on_second_delete():
    agent_id = routes.registry.register("cleanup-agent", "worker.cleanup")

    assert asyncio.run(routes.delete_agent(agent_id))["status"] == "deleted"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.delete_agent(agent_id))

    assert exc.value.status_code == 404


def test_same_key_cannot_be_reused_for_different_resource():
    first = routes.registry.register("agent-1", "worker.cleanup")
    second = routes.registry.register("agent-2", "worker.cleanup")

    asyncio.run(routes.delete_agent(first, idempotency_key="same-key"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.delete_agent(second, idempotency_key="same-key"))

    assert exc.value.status_code == 409
    assert routes.registry.get(second) is not None


def test_expired_key_allows_new_request_after_ttl():
    now = {"value": 100.0}
    routes.destructive_idempotency = DestructiveActionIdempotencyStore(
        clock=lambda: now["value"],
        ttl=10.0,
    )
    first = routes.registry.register("agent-1", "worker.cleanup")
    second = routes.registry.register("agent-2", "worker.cleanup")

    asyncio.run(routes.delete_agent(first, idempotency_key="expiring-key"))
    now["value"] = 111.0
    result = asyncio.run(
        routes.delete_agent(second, idempotency_key="expiring-key")
    )

    assert result == {"status": "deleted", "agent_id": second}
    actions = [
        event["action"]
        for event in routes.destructive_idempotency.audit_report()
    ]
    assert "expired" in actions


def test_store_conflict_does_not_expose_raw_key_in_audit():
    store = DestructiveActionIdempotencyStore(clock=lambda: 1.0)
    store.execute("raw-secret-key", "delete:/a", lambda: {"ok": True})

    with pytest.raises(IdempotencyConflictError):
        store.execute("raw-secret-key", "delete:/b", lambda: {"ok": True})

    audit_text = str(store.audit_report())
    assert "raw-secret-key" not in audit_text
    assert "conflict" in audit_text


def test_sdk_delete_agent_sends_idempotency_key(monkeypatch):
    captured = {}

    def fake_request(self, method, path, data=None, extra_headers=None):
        captured["method"] = method
        captured["path"] = path
        captured["headers"] = extra_headers
        return {"status": "deleted"}

    monkeypatch.setattr(
        OrchestratorClient,
        "_request",
        fake_request,
    )
    client = OrchestratorClient(
        base_url="https://example.invalid",
        api_key="k",
    )

    assert client.delete_agent("agent-1", idempotency_key="delete-1") == {
        "status": "deleted"
    }
    assert captured == {
        "method": "DELETE",
        "path": "/agents/agent-1",
        "headers": {"Idempotency-Key": "delete-1"},
    }
