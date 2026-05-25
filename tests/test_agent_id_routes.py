from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent.registry import (
    AgentIdentifierError,
    AgentRegistry,
    normalize_agent_id,
)
from src.api import routes


def create_client():
    routes.registry = AgentRegistry()
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v2")
    return TestClient(app)


def register_agent(client):
    response = client.post(
        "/api/v2/agents",
        params={"name": "worker", "agent_type": "worker.processor"},
    )
    assert response.status_code == 200
    return response.json()["agent_id"]


def test_mixed_case_agent_id_matches_existing_agent_before_lookup():
    client = create_client()
    agent_id = register_agent(client)
    mixed_case_id = agent_id.upper()

    response = client.get(f"/api/v2/agents/{mixed_case_id}")

    assert response.status_code == 200
    assert response.json()["id"] == agent_id


def test_malformed_agent_id_returns_400_without_lookup(monkeypatch):
    client = create_client()
    called = False

    def fail_if_called(agent_id):
        nonlocal called
        called = True
        raise AssertionError("registry lookup should not run")

    monkeypatch.setattr(routes.registry, "get", fail_if_called)

    response = client.get("/api/v2/agents/not-a-uuid")

    assert response.status_code == 400
    assert not called


def test_mixed_case_agent_id_can_start_and_stop_agent():
    client = create_client()
    agent_id = register_agent(client)
    mixed_case_id = agent_id.upper()

    start = client.post(f"/api/v2/agents/{mixed_case_id}/start")
    read_started = client.get(f"/api/v2/agents/{agent_id}")
    stop = client.post(f"/api/v2/agents/{mixed_case_id}/stop")
    read_stopped = client.get(f"/api/v2/agents/{agent_id}")

    assert start.status_code == 200
    assert read_started.json()["status"] == "running"
    assert stop.status_code == 200
    assert read_stopped.json()["status"] == "paused"


def test_delete_normalizes_agent_id_before_mutation():
    client = create_client()
    agent_id = register_agent(client)
    mixed_case_id = agent_id.upper()

    deleted = client.delete(f"/api/v2/agents/{mixed_case_id}")
    read_after_delete = client.get(f"/api/v2/agents/{agent_id}")

    assert deleted.status_code == 200
    assert read_after_delete.status_code == 404


def test_normalizer_rejects_malformed_id_consistently():
    try:
        normalize_agent_id("not-a-uuid")
    except AgentIdentifierError:
        pass
    else:
        raise AssertionError("malformed agent id should fail closed")
