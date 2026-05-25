import pytest

from src.release.rollback import (
    ReleaseRollbackError,
    ReleaseRollbackManager,
)


def build_manager(events, startup_ok=True, queue_ok=True):
    return ReleaseRollbackManager(
        restore_config=lambda snapshot: events.append(
            ("config", snapshot.to_dict()),
        ),
        restore_image=lambda snapshot: events.append(
            ("image", snapshot.to_dict()),
        ),
        verify_startup=lambda snapshot: startup_ok,
        verify_queue=lambda snapshot: queue_ok,
    )


def test_records_image_and_config_digests_together():
    events = []
    manager = build_manager(events)

    snapshot = manager.record_release(
        version="v2.4.0",
        image_digest="sha256:image-a",
        config_digest="sha256:config-a",
    )

    assert snapshot.to_dict() == {
        "version": "v2.4.0",
        "image_digest": "sha256:image-a",
        "config_digest": "sha256:config-a",
    }
    assert manager.release_history() == [snapshot.to_dict()]


def test_rollback_restores_matching_config_and_image_pair():
    events = []
    manager = build_manager(events)
    manager.record_release("v2.4.0", "sha256:image-a", "sha256:config-a")
    manager.record_release("v2.5.0", "sha256:image-b", "sha256:config-b")

    restored = manager.rollback_to("v2.4.0")

    expected = {
        "version": "v2.4.0",
        "image_digest": "sha256:image-a",
        "config_digest": "sha256:config-a",
    }
    assert restored.to_dict() == expected
    assert manager.current_snapshot().to_dict() == expected
    assert events == [("config", expected), ("image", expected)]


def test_rollback_requires_startup_verification():
    events = []
    manager = build_manager(events, startup_ok=False)
    manager.record_release("v2.4.0", "sha256:image-a", "sha256:config-a")
    manager.record_release("v2.5.0", "sha256:image-b", "sha256:config-b")

    with pytest.raises(
        ReleaseRollbackError,
        match="startup verification failed",
    ):
        manager.rollback_to("v2.4.0")

    assert manager.current_snapshot().version == "v2.5.0"


def test_rollback_requires_queue_connectivity_verification():
    events = []
    manager = build_manager(events, queue_ok=False)
    manager.record_release("v2.4.0", "sha256:image-a", "sha256:config-a")
    manager.record_release("v2.5.0", "sha256:image-b", "sha256:config-b")

    with pytest.raises(
        ReleaseRollbackError,
        match="queue verification failed",
    ):
        manager.rollback_to("v2.4.0")

    assert manager.current_snapshot().version == "v2.5.0"


def test_unknown_release_version_is_rejected():
    events = []
    manager = build_manager(events)

    with pytest.raises(ReleaseRollbackError, match="unknown release version"):
        manager.rollback_to("missing")
