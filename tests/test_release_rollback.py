import pytest

from src.deploy.rollback import (
    ReleaseRollbackManager,
    RollbackVerificationError,
    config_digest,
)


def test_record_release_pairs_image_and_configuration_digests():
    manager = ReleaseRollbackManager()
    config = {"feature": {"enabled": True}, "queue": {"url": "redis://old"}}

    manifest = manager.record_release(
        "v1.0.0",
        image_digest="sha256:image-old",
        config=config,
    )

    assert manifest.image_digest == "sha256:image-old"
    assert manifest.config_digest == config_digest(config)
    assert manifest.config_snapshot == config
    assert manager.current_version == "v1.0.0"


def test_rollback_restores_matching_config_snapshot_with_image():
    manager = ReleaseRollbackManager()
    old_config = {
        "feature": {"enabled": False},
        "queue": {"url": "redis://old"},
    }
    new_config = {
        "feature": {"enabled": True},
        "queue": {"url": "redis://new"},
    }
    manager.record_release("v1.0.0", "sha256:old", old_config)
    manager.record_release("v2.0.0", "sha256:new", new_config)

    restored = manager.rollback_to("v1.0.0")

    assert restored.version == "v1.0.0"
    assert manager.current_image_digest == "sha256:old"
    assert manager.current_config == old_config


def test_rollback_verifies_startup_and_queue_connectivity():
    verified = []

    def startup_check(manifest):
        verified.append(("startup", manifest.version))
        return True

    def queue_check(manifest):
        verified.append(("queue", manifest.version))
        return True

    manager = ReleaseRollbackManager(
        startup_check=startup_check,
        queue_check=queue_check,
    )
    manager.record_release("v1.0.0", "sha256:old", {"queue": "old"})
    manager.record_release("v2.0.0", "sha256:new", {"queue": "new"})

    manager.rollback_to("v1.0.0")

    assert verified == [
        ("startup", "v1.0.0"),
        ("queue", "v1.0.0"),
    ]


def test_failed_rollback_verification_preserves_active_release():
    manager = ReleaseRollbackManager(queue_check=lambda manifest: False)
    manager.record_release("v1.0.0", "sha256:old", {"queue": "old"})
    manager.record_release("v2.0.0", "sha256:new", {"queue": "new"})

    with pytest.raises(RollbackVerificationError, match="queue connectivity"):
        manager.rollback_to("v1.0.0")

    assert manager.current_version == "v2.0.0"
    assert manager.current_image_digest == "sha256:new"
    assert manager.current_config == {"queue": "new"}


def test_tampered_config_snapshot_fails_before_switching_release():
    manager = ReleaseRollbackManager()
    manager.record_release("v1.0.0", "sha256:old", {"flag": False})
    manager.record_release("v2.0.0", "sha256:new", {"flag": True})
    manifest = manager.get_manifest("v1.0.0")
    manifest.config_snapshot["flag"] = "tampered"

    with pytest.raises(RollbackVerificationError, match="digest mismatch"):
        manager.rollback_to("v1.0.0")

    assert manager.current_version == "v2.0.0"
    assert manager.current_config == {"flag": True}
