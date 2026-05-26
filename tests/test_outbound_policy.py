import pytest

from src.security.outbound import (
    OutboundRequestPolicy,
    OutboundRequestPolicyError,
    canonicalize_hostname,
)


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("Example.COM.", "example.com"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("bücher.example", "xn--bcher-kva.example"),
        ("%65xample.com", "example.com"),
    ],
)
def test_canonicalize_hostname_normalizes_policy_inputs(hostname, expected):
    assert canonicalize_hostname(hostname) == expected


def test_allowlist_compares_canonical_hosts():
    policy = OutboundRequestPolicy(["example.com", "bücher.example"])

    assert policy.is_allowed("https://EXAMPLE.com./api")
    assert policy.is_allowed("https://xn--bcher-kva.example/callback")
    assert policy.is_allowed("https://b%C3%BCcher.example/callback")

    assert policy.audit_events[-1] == {
        "url_scheme": "https",
        "normalized_host": "xn--bcher-kva.example",
        "allowed": True,
        "reason": "allowed",
    }


def test_denied_host_fails_before_network_dispatch():
    policy = OutboundRequestPolicy(["api.example.com"])
    dispatched = []

    def dispatcher(url):
        dispatched.append(url)
        return "called"

    with pytest.raises(OutboundRequestPolicyError, match="not allowed"):
        policy.dispatch("https://evil.example.net/task", dispatcher)

    assert dispatched == []
    assert policy.audit_events[-1] == {
        "url_scheme": "https",
        "normalized_host": "evil.example.net",
        "allowed": False,
        "reason": "host_not_allowed",
    }


def test_audit_report_summarizes_without_raw_url_secrets():
    policy = OutboundRequestPolicy(["api.example.com"])

    assert policy.is_allowed(
        "https://user:token@API.EXAMPLE.COM./task?a=secret"
    )
    with pytest.raises(OutboundRequestPolicyError) as error:
        policy.dispatch(
            "https://user:private@evil.example.net/task?token=secret",
            lambda url: "called",
        )

    report = policy.audit_report()

    assert report["total"] == 2
    assert report["allowed"] == 1
    assert report["denied"] == 1
    assert report["by_reason"] == {"allowed": 1, "host_not_allowed": 1}
    assert report["by_normalized_host"] == {
        "api.example.com": 1,
        "evil.example.net": 1,
    }
    assert "evil.example.net" in str(error.value)
    assert "user:" not in str(error.value)
    assert "private" not in str(error.value)
    assert "token=secret" not in str(report)

    report["recent"][0]["reason"] = "changed"
    assert policy.audit_events[0]["reason"] == "allowed"


def test_allowed_host_dispatches_after_policy_check():
    policy = OutboundRequestPolicy(["api.example.com."])

    result = policy.dispatch(
        "https://API.EXAMPLE.COM./task",
        lambda url: {"url": url},
    )

    assert result == {"url": "https://API.EXAMPLE.COM./task"}


@pytest.mark.parametrize(
    "hostname",
    [
        "",
        "example.com/path",
        "example.com\\path",
        "user@example.com",
    ],
)
def test_invalid_hostnames_are_rejected(hostname):
    with pytest.raises(OutboundRequestPolicyError):
        canonicalize_hostname(hostname)
