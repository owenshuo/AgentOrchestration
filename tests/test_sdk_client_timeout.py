from unittest.mock import patch

from src.sdk.client import OrchestratorClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"agents": []}'


def test_sdk_request_passes_default_timeout_to_urlopen():
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )

    with patch(
        "src.sdk.client.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        response = client.list_agents()

    assert response == {"agents": []}
    assert urlopen.call_args.kwargs["timeout"] == 30.0


def test_sdk_request_uses_configurable_timeout():
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
        timeout=2.5,
    )

    with patch(
        "src.sdk.client.urlopen",
        return_value=FakeResponse(),
    ) as urlopen:
        client.get_agent("agent-1")

    assert urlopen.call_args.kwargs["timeout"] == 2.5
