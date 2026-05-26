import jwt
import pytest

from src.api.embedded_console import (
    EmbeddedConsoleAuthError,
    EmbeddedConsoleIssuer,
    EmbeddedConsoleSessionExchange,
)


def make_exchange():
    return EmbeddedConsoleSessionExchange(
        issuers=[
            EmbeddedConsoleIssuer(
                issuer="https://dashboard.example",
                secret="dashboard-secret",
                audience="ao:embedded-console",
                allowed_tenants={"tenant-a", "tenant-b"},
            ),
            EmbeddedConsoleIssuer(
                issuer="https://partner.example",
                secret="partner-secret",
                audience="ao:partner-console",
                allowed_tenants={"tenant-c"},
            ),
        ],
        clock=lambda: 1000.0,
        max_session_ttl=300,
    )


def sign_token(
    issuer="https://dashboard.example",
    secret="dashboard-secret",
    audience="ao:embedded-console",
    tenant_id="tenant-a",
    subject="admin-1",
    expires_at=1200,
):
    return jwt.encode(
        {
            "iss": issuer,
            "sub": subject,
            "aud": audience,
            "tenant_id": tenant_id,
            "exp": expires_at,
        },
        secret,
        algorithm="HS256",
    )


def test_valid_embedded_console_token_creates_bounded_session():
    exchange = make_exchange()
    token = sign_token(expires_at=2000)

    session = exchange.exchange(token, tenant_id="tenant-a")

    assert session.tenant_id == "tenant-a"
    assert session.issuer == "https://dashboard.example"
    assert session.subject == "admin-1"
    assert session.audience == "ao:embedded-console"
    assert session.expires_at == 1300.0
    assert exchange.get_session(session.id) is session


def test_wrong_audience_is_rejected_before_session_creation():
    exchange = make_exchange()
    token = sign_token(audience="ao:other-integration")

    with pytest.raises(EmbeddedConsoleAuthError, match="invalid audience"):
        exchange.exchange(token, tenant_id="tenant-a")

    assert exchange.audit_report()[-1]["details"]["reason"] == (
        "invalid_audience"
    )
    assert exchange.audit_report()[-1]["action"] == "session_rejected"


def test_tenant_mismatch_fails_before_session_creation():
    exchange = make_exchange()
    token = sign_token(tenant_id="tenant-b")

    with pytest.raises(EmbeddedConsoleAuthError, match="tenant mismatch"):
        exchange.exchange(token, tenant_id="tenant-a")

    assert exchange.audit_report()[-1]["details"]["reason"] == (
        "tenant_mismatch"
    )
    assert exchange.get_session("missing") is None


def test_expired_token_is_rejected():
    exchange = make_exchange()
    token = sign_token(expires_at=900)

    with pytest.raises(EmbeddedConsoleAuthError, match="token expired"):
        exchange.exchange(token, tenant_id="tenant-a")

    assert exchange.audit_report()[-1]["details"]["reason"] == "token_expired"


def test_multi_issuer_tokens_require_their_own_audience_and_secret():
    exchange = make_exchange()
    partner_token = sign_token(
        issuer="https://partner.example",
        secret="partner-secret",
        audience="ao:partner-console",
        tenant_id="tenant-c",
        subject="partner-admin",
    )

    session = exchange.exchange(partner_token, tenant_id="tenant-c")

    assert session.issuer == "https://partner.example"
    assert session.audience == "ao:partner-console"
    assert session.subject == "partner-admin"


def test_multi_issuer_wrong_audience_is_not_accepted_cross_issuer():
    exchange = make_exchange()
    token = sign_token(
        issuer="https://partner.example",
        secret="partner-secret",
        audience="ao:embedded-console",
        tenant_id="tenant-c",
    )

    with pytest.raises(EmbeddedConsoleAuthError, match="invalid audience"):
        exchange.exchange(token, tenant_id="tenant-c")


def test_untrusted_issuer_is_rejected():
    exchange = make_exchange()
    token = sign_token(
        issuer="https://evil.example",
        secret="evil-secret",
        audience="ao:embedded-console",
    )

    with pytest.raises(EmbeddedConsoleAuthError, match="issuer"):
        exchange.exchange(token, tenant_id="tenant-a")

    assert exchange.audit_report()[-1]["details"]["reason"] == (
        "unknown_issuer"
    )


def test_audit_never_includes_raw_token_or_secret():
    exchange = make_exchange()
    token = sign_token(audience="ao:other-integration")

    with pytest.raises(EmbeddedConsoleAuthError):
        exchange.exchange(token, tenant_id="tenant-a")

    audit_text = str(exchange.audit_report())
    assert token not in audit_text
    assert "dashboard-secret" not in audit_text
    assert "partner-secret" not in audit_text
