import pytest

from src.common.storage import ArtifactIndexStore


class ManualClock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_deleting_artifact_removes_derived_search_metadata():
    store = ArtifactIndexStore()
    store.put_artifact("artifact-1", {"body": "source"})
    store.put_derived_index(
        "idx-1",
        "artifact-1",
        {"terms": ["source"], "private": "kept-in-index-only"},
    )
    store.put_derived_index("idx-2", "artifact-1", {"terms": ["task"]})

    assert store.delete_artifact("artifact-1")

    assert store.get_artifact("artifact-1") is None
    assert store.get_derived_index("idx-1") is None
    assert store.get_derived_index("idx-2") is None
    assert store.derived_index_ids() == []


def test_retention_reconciliation_cascades_to_derived_indexes():
    clock = ManualClock()
    store = ArtifactIndexStore(clock=clock)
    store.put_artifact("expired", {"body": "old"}, retention_seconds=10)
    store.put_derived_index("idx-expired", "expired", {"terms": ["old"]})
    store.put_artifact("kept", {"body": "new"}, retention_seconds=30)
    store.put_derived_index("idx-kept", "kept", {"terms": ["new"]})

    clock.advance(10)
    report = store.reconcile_retention()

    assert report == {
        "expired_artifacts": ["expired"],
        "stale_derived_indexes": [],
    }
    assert store.artifact_ids() == ["kept"]
    assert store.derived_index_ids() == ["idx-kept"]


def test_reconciliation_reports_and_removes_orphan_derived_records():
    store = ArtifactIndexStore()
    store.put_artifact("artifact-1", {"body": "source"})
    store.put_derived_index("idx-1", "artifact-1", {"terms": ["source"]})

    store._artifacts.pop("artifact-1")
    report = store.reconcile_retention()

    assert report == {
        "expired_artifacts": [],
        "stale_derived_indexes": ["idx-1"],
    }
    assert store.derived_index_ids() == []


def test_retention_report_previews_cleanup_without_payload_metadata():
    clock = ManualClock()
    store = ArtifactIndexStore(clock=clock)
    store.put_artifact(
        "expired",
        {"body": "private-source"},
        retention_seconds=5,
    )
    store.put_derived_index(
        "idx-expired",
        "expired",
        {"terms": ["private-index"]},
    )
    store.put_artifact("kept", {"body": "public"}, retention_seconds=30)
    store.put_derived_index("idx-orphan", "kept", {"terms": ["orphaned"]})

    store._artifacts.pop("kept")
    clock.advance(5)

    report = store.retention_report()

    assert report == {
        "expired_artifacts": ["expired"],
        "stale_derived_indexes": ["idx-orphan"],
        "counts": {
            "artifacts": 1,
            "derived_indexes": 2,
            "expired_artifacts": 1,
            "stale_derived_indexes": 1,
        },
    }
    assert store.artifact_ids() == ["expired"]
    assert store.derived_index_ids() == ["idx-expired", "idx-orphan"]
    assert "private-source" not in str(report)
    assert "private-index" not in str(report)
    assert "orphaned" not in str(report)

    cleanup_report = store.reconcile_retention()

    assert cleanup_report == {
        "expired_artifacts": ["expired"],
        "stale_derived_indexes": ["idx-orphan"],
    }
    assert store.artifact_ids() == []
    assert store.derived_index_ids() == []


def test_reindexing_moves_derived_record_between_artifacts():
    store = ArtifactIndexStore()
    store.put_artifact("artifact-1", {"body": "first"})
    store.put_artifact("artifact-2", {"body": "second"})
    store.put_derived_index("idx-shared", "artifact-1", {"terms": ["first"]})

    store.put_derived_index("idx-shared", "artifact-2", {"terms": ["second"]})
    store.delete_artifact("artifact-1")

    assert store.get_derived_index("idx-shared") == {"terms": ["second"]}


def test_index_requires_existing_artifact_and_valid_retention():
    store = ArtifactIndexStore()

    with pytest.raises(KeyError, match="artifact must exist"):
        store.put_derived_index("idx-missing", "missing", {})

    with pytest.raises(ValueError, match="retention_seconds"):
        store.put_artifact("bad", {}, retention_seconds=-1)
