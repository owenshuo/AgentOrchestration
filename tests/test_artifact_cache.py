import hashlib

import pytest

from src.storage.artifact_cache import ArtifactDownloadCache


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_cache_hit_validates_digest_before_reuse(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"good-content")
    cache.add_entry("artifact-1", artifact, digest(b"good-content"))

    assert cache.get("artifact-1") == artifact


def test_persisted_metadata_validates_digest_after_restart(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)

    def downloader(target):
        target.write_bytes(b"good-content")

    restored = cache.get_or_download(
        "artifact-1",
        expected_digest=digest(b"good-content"),
        downloader=downloader,
    )

    restarted_cache = ArtifactDownloadCache(tmp_path)
    assert restarted_cache.get("artifact-1") == restored


def test_metadata_loss_evicts_cached_artifact(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"good-content")
    cache.add_entry("artifact-1", artifact, digest(b"good-content"))
    for metadata_path in tmp_path.glob("*.metadata.json"):
        metadata_path.unlink()

    restarted_cache = ArtifactDownloadCache(tmp_path)

    assert restarted_cache.get("artifact-1") is None
    assert artifact.exists()


def test_digest_mismatch_evicts_and_redownloads(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"corrupt-content")
    cache.add_entry("artifact-1", artifact, digest(b"good-content"))
    calls = []

    def downloader(target):
        calls.append(target)
        target.write_bytes(b"good-content")

    restored = cache.get_or_download(
        "artifact-1",
        expected_digest=digest(b"good-content"),
        downloader=downloader,
    )

    assert restored.read_bytes() == b"good-content"
    assert calls[0].name.endswith(".download")
    assert calls[0] != restored
    assert cache.evictions == [
        {"key": "artifact-1", "reason": "cache_validation_failed"}
    ]


def test_download_uses_temporary_file_until_validated(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)

    def downloader(target):
        assert target.name.endswith(".download")
        target.write_bytes(b"good-content")

    restored = cache.get_or_download(
        "artifact-1",
        expected_digest=digest(b"good-content"),
        downloader=downloader,
    )

    assert restored.read_bytes() == b"good-content"
    assert not list(tmp_path.glob("*.download"))


def test_partial_file_evicts_and_redownloads(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"part")
    cache.add_entry(
        "artifact-1",
        artifact,
        expected_digest=digest(b"complete"),
        expected_size=len(b"complete"),
    )

    def downloader(target):
        target.write_bytes(b"complete")

    restored = cache.get_or_download(
        "artifact-1",
        expected_digest=digest(b"complete"),
        expected_size=len(b"complete"),
        downloader=downloader,
    )

    assert restored.read_bytes() == b"complete"
    assert cache.evictions[-1]["reason"] == "cache_validation_failed"


def test_invalid_download_is_not_cached(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)

    def downloader(target):
        target.write_bytes(b"wrong")

    with pytest.raises(ValueError, match="failed checksum"):
        cache.get_or_download(
            "artifact-1",
            expected_digest=digest(b"right"),
            downloader=downloader,
        )

    assert cache.get("artifact-1") is None
    assert list(tmp_path.iterdir()) == []


def test_missing_cached_file_is_evicted(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"content")
    cache.add_entry("artifact-1", artifact, digest(b"content"))
    artifact.unlink()

    assert cache.get("artifact-1") is None
    assert cache.evictions[-1]["key"] == "artifact-1"
