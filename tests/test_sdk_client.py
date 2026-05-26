import json

from src.sdk.client import OrchestratorClient


class _Response:
    def __init__(self, payload=b"", status=200):
        self._payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._payload


def test_request_returns_empty_dict_for_204_no_content(monkeypatch):
    def fake_urlopen(request):
        assert request.get_method() == "DELETE"
        return _Response(status=204)

    monkeypatch.setattr("src.sdk.client.urlopen", fake_urlopen)

    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.delete_agent("agent-1") == {}


def test_request_returns_empty_dict_for_empty_success_body(monkeypatch):
    monkeypatch.setattr(
        "src.sdk.client.urlopen",
        lambda request: _Response(b"", status=200),
    )

    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.stop_agent("agent-1") == {}


def test_request_returns_empty_dict_for_whitespace_success_body(monkeypatch):
    monkeypatch.setattr(
        "src.sdk.client.urlopen",
        lambda request: _Response(b" \n\t ", status=202),
    )

    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.stop_agent("agent-1") == {}


def test_request_still_decodes_json_success_body(monkeypatch):
    expected = {"id": "agent-1", "status": "deleted"}
    payload = json.dumps(expected).encode()
    monkeypatch.setattr(
        "src.sdk.client.urlopen",
        lambda request: _Response(payload, status=200),
    )

    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    assert client.delete_agent("agent-1") == expected
