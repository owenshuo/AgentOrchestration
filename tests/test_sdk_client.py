from src.sdk import client as client_module
from src.sdk.client import OrchestratorClient


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self._body


def test_delete_agent_accepts_204_no_content(monkeypatch):
    captured = {}

    def fake_urlopen(req):
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        return FakeResponse(status=204)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.delete_agent("agent-123") == {}
    assert captured == {
        "method": "DELETE",
        "url": "https://example.test/api/v2/agents/agent-123",
    }


def test_empty_success_body_returns_stable_empty_result(monkeypatch):
    def fake_urlopen(req):
        return FakeResponse(status=200, body=b" \n\t")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.stop_agent("agent-123") == {}


def test_json_success_body_still_decodes(monkeypatch):
    def fake_urlopen(req):
        return FakeResponse(
            status=200,
            body=b'{"id": "agent-123", "status": "running"}',
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.get_agent("agent-123") == {
        "id": "agent-123",
        "status": "running",
    }
