import pytest

from src.common.quarantine import ValidationQuarantineStore


def test_quarantine_record_has_expiration_and_redacted_view():
    now = [100.0]
    store = ValidationQuarantineStore(
        ttl_seconds=60.0,
        clock=lambda: now[0],
    )

    record = store.add(
        {
            "task": "create-agent",
            "token": "secret-token",
            "nested": {"password": "secret-password", "name": "safe"},
        },
        reason="schema_error",
    )

    view = store.get(record.record_id)

    assert view["expires_at"] == 160.0
    assert view["payload"] == {
        "task": "create-agent",
        "token": "[REDACTED]",
        "nested": {"password": "[REDACTED]", "name": "safe"},
    }
    assert store.audit_records[0]["action"] == "stored"
    assert store.audit_records[0]["component"] == "validation_quarantine"


def test_cleanup_removes_expired_records():
    now = [10.0]
    store = ValidationQuarantineStore(ttl_seconds=5.0, clock=lambda: now[0])
    record = store.add({"payload": "bad"}, reason="schema_error")

    now[0] = 15.0

    assert store.cleanup_expired() == 1
    assert store.get(record.record_id) is None
    assert store.audit_records[-1]["action"] == "expired"


def test_raw_payload_requires_record_access_token():
    store = ValidationQuarantineStore()
    record = store.add({"token": "secret-token"}, reason="schema_error")

    with pytest.raises(PermissionError):
        store.get(record.record_id, include_payload=True)

    raw_view = store.get(
        record.record_id,
        include_payload=True,
        access_token=record.access_token,
    )

    assert raw_view["payload"] == {"token": "secret-token"}
    assert store.audit_records[-1]["action"] == "raw_accessed"


def test_list_records_omits_expired_records_and_raw_payloads():
    now = [1.0]
    store = ValidationQuarantineStore(ttl_seconds=2.0, clock=lambda: now[0])
    store.add({"password": "one"}, reason="schema_error")
    kept = store.add({"password": "two"}, reason="schema_error")

    now[0] = 3.0
    kept.expires_at = 10.0

    records = store.list_records()

    assert [record["record_id"] for record in records] == [kept.record_id]
    assert records[0]["payload"] == {"password": "[REDACTED]"}
