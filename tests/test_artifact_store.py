"""Regression tests for digest-safe artifact deduplication."""

import pytest

from src.storage.artifact_store import (
    ArtifactDigestMismatchError,
    ContentAddressedArtifactStore,
    sha256_digest,
)


def test_same_name_different_content_creates_distinct_blobs(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)

    first = store.put("report.csv", b"amount,status\n1,open\n")
    second = store.put("report.csv", b"amount,status\n2,closed\n")

    assert first.artifact_id != second.artifact_id
    assert first.content_digest != second.content_digest
    assert first.blob.path != second.blob.path
    assert store.blob_count() == 2
    assert store.artifact_count() == 2
    assert store.latest("report.csv") == second
    assert store.read(first.artifact_id) == b"amount,status\n1,open\n"
    assert store.read(second.artifact_id) == b"amount,status\n2,closed\n"


def test_same_name_same_content_dedups_by_verified_digest(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    content = b"identical artifact bytes"

    first = store.put("artifact.bin", content)
    second = store.put("artifact.bin", content)

    assert first == second
    assert store.blob_count() == 1
    assert store.artifact_count() == 1


def test_different_names_share_immutable_blob_but_keep_metadata(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    content = b"shared bytes"

    alpha = store.put("alpha.txt", content, metadata={"owner": "alpha"})
    beta = store.put("beta.txt", content, metadata={"owner": "beta"})

    assert alpha.artifact_id != beta.artifact_id
    assert alpha.blob == beta.blob
    assert alpha.metadata["owner"] == "alpha"
    assert beta.metadata["owner"] == "beta"
    assert store.blob_count() == 1
    assert store.artifact_count() == 2


def test_claimed_digest_mismatch_stores_blob_but_rejects_metadata(
    tmp_path,
):
    store = ContentAddressedArtifactStore(tmp_path)
    content = b"real payload"
    claimed_digest = sha256_digest(b"different payload")

    with pytest.raises(ArtifactDigestMismatchError) as exc_info:
        store.put("invoice.pdf", content, claimed_digest=claimed_digest)

    error = exc_info.value
    assert error.claimed_digest == claimed_digest
    assert error.verified_digest == sha256_digest(content)
    assert error.blob.digest == sha256_digest(content)
    assert store.blob_count() == 1
    assert store.artifact_count() == 0
    assert store.latest("invoice.pdf") is None


def test_claimed_digest_match_links_metadata(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    content = b"trusted payload"

    artifact = store.put(
        "payload.bin",
        content,
        claimed_digest=sha256_digest(content),
    )

    assert artifact.content_digest == sha256_digest(content)
    assert store.latest("payload.bin") == artifact
    assert store.verify(artifact.artifact_id)


def test_tampered_blob_fails_verification(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put("payload.bin", b"original")

    blob_path = (
        tmp_path
        / "blobs"
        / artifact.content_digest[:2]
        / artifact.content_digest
    )
    blob_path.chmod(0o644)
    blob_path.write_bytes(b"tampered")

    assert not store.verify(artifact.artifact_id)
