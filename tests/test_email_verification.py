import pytest

from src.common.email_verification import (
    EmailVerificationError,
    VerifiedEmailClaimStore,
    canonicalize_verified_email,
)


def test_gmail_case_dot_plus_and_googlemail_aliases_conflict():
    claims = VerifiedEmailClaimStore(clock=lambda: 10.0)

    created = claims.claim("user-1", "First.Last+tag@GoogleMail.com")

    assert created.canonical_email == "firstlast@gmail.com"
    assert created.provider == "gmail"
    with pytest.raises(EmailVerificationError, match="already claimed"):
        claims.claim("user-2", "firstlast+other@gmail.com")
    assert claims.owner_for("f.i.r.s.t.l.a.s.t@gmail.com") == "user-1"


def test_same_user_reverify_is_idempotent_and_updates_metadata():
    ticks = iter([10.0, 10.0, 20.0, 20.0])
    claims = VerifiedEmailClaimStore(clock=lambda: next(ticks))

    first = claims.claim("user-1", "Name+old@gmail.com")
    second = claims.claim("user-1", "n.a.m.e+new@googlemail.com")

    assert first is second
    assert second.claim_count == 2
    assert second.verified_at == 10.0
    assert second.last_seen_at == 20.0


def test_outlook_plus_alias_conflicts_but_dots_are_preserved():
    claims = VerifiedEmailClaimStore()

    claims.claim("user-1", "first.last+tag@outlook.com")

    with pytest.raises(EmailVerificationError):
        claims.claim("user-2", "FIRST.LAST@outlook.com")
    assert claims.claim("user-2", "firstlast@outlook.com").canonical_email == (
        "firstlast@outlook.com"
    )


def test_generic_domains_only_lowercase_without_dot_or_plus_policy():
    claims = VerifiedEmailClaimStore()

    claims.claim("user-1", "First.Last+tag@example.com")

    second = claims.claim("user-2", "first.last@example.com")
    assert second.canonical_email == "first.last@example.com"
    owner = claims.owner_for("FIRST.LAST+TAG@example.com")
    assert owner == "user-1"


def test_revoke_removes_canonical_claim_only_for_owner():
    claims = VerifiedEmailClaimStore()
    claims.claim("user-1", "name@gmail.com")

    assert not claims.revoke("user-2", "n.a.m.e@gmail.com")
    assert claims.owner_for("name@gmail.com") == "user-1"
    assert claims.revoke("user-1", "n.a.m.e@gmail.com")
    assert claims.owner_for("name@gmail.com") is None


def test_audit_report_documents_policy_without_raw_email_or_secrets():
    claims = VerifiedEmailClaimStore(clock=lambda: 10.0)
    claims.claim("user-1", "First.Last+tag@gmail.com")
    with pytest.raises(EmailVerificationError):
        claims.claim("user-2", "firstlast@gmail.com")

    audit = claims.audit_report()

    assert [event["action"] for event in audit] == [
        "claim_created",
        "duplicate_rejected",
    ]
    assert audit[0]["canonical_email"] == "firstlast@gmail.com"
    assert audit[0]["ignored_alias_parts"] == ["dots", "plus_tag"]
    assert "First.Last+tag" not in str(audit)
    assert "secret" not in str(audit).lower()
    assert "token" not in str(audit).lower()


@pytest.mark.parametrize(
    "email",
    ["", "no-at", "a@@b.com", "@example.com", "name@", "na me@example.com"],
)
def test_invalid_email_rejected(email):
    with pytest.raises(EmailVerificationError):
        canonicalize_verified_email(email)


def test_canonical_policy_view_is_explicit_for_provider_rules():
    policy = canonicalize_verified_email("A.B+tag@gmail.com").public_policy()

    assert policy == {
        "canonical": "ab@gmail.com",
        "provider": "gmail",
        "ignored_alias_parts": ["dots", "plus_tag"],
    }
