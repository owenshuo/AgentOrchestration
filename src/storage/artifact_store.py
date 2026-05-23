"""Content-addressed artifact storage with digest-safe deduplication."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import os
from typing import Dict, Mapping, Optional, Tuple
from uuid import uuid4


@dataclass(frozen=True)
class BlobRef:
    """Immutable reference to bytes stored by verified content digest."""

    digest: str
    size: int
    path: str


@dataclass(frozen=True)
class ArtifactMetadata:
    """Logical artifact metadata linked to an immutable blob reference."""

    artifact_id: str
    logical_name: str
    content_digest: str
    blob: BlobRef
    metadata: Mapping[str, str] = field(default_factory=dict)


class ArtifactDigestMismatchError(ValueError):
    """Raised when supplied metadata tries to reuse the wrong digest."""

    def __init__(
        self,
        logical_name: str,
        claimed_digest: str,
        verified_digest: str,
        blob: BlobRef,
    ):
        super().__init__(
            "Artifact digest mismatch "
            f"(logical_name={logical_name}, "
            f"claimed_digest={claimed_digest}, "
            f"verified_digest={verified_digest})"
        )
        self.logical_name = logical_name
        self.claimed_digest = claimed_digest
        self.verified_digest = verified_digest
        self.blob = blob


class ContentAddressedArtifactStore:
    """Store artifact metadata only after verifying content digests."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._blobs: Dict[str, BlobRef] = {}
        self._artifacts: Dict[str, ArtifactMetadata] = {}
        self._dedup_index: Dict[Tuple[str, str], str] = {}
        self._latest_by_name: Dict[str, str] = {}

    def put(
        self,
        logical_name: str,
        content: bytes,
        claimed_digest: Optional[str] = None,
        metadata: Optional[Mapping[str, str]] = None,
    ) -> ArtifactMetadata:
        """Persist bytes and link metadata using the verified digest."""
        verified_digest = sha256_digest(content)
        blob = self._ensure_blob(verified_digest, content)

        if claimed_digest and claimed_digest != verified_digest:
            raise ArtifactDigestMismatchError(
                logical_name=logical_name,
                claimed_digest=claimed_digest,
                verified_digest=verified_digest,
                blob=blob,
            )

        dedup_key = (logical_name, verified_digest)
        artifact_id = self._dedup_index.get(dedup_key)
        if artifact_id:
            return self._artifacts[artifact_id]

        artifact = ArtifactMetadata(
            artifact_id=str(uuid4()),
            logical_name=logical_name,
            content_digest=verified_digest,
            blob=blob,
            metadata=dict(metadata or {}),
        )
        self._artifacts[artifact.artifact_id] = artifact
        self._dedup_index[dedup_key] = artifact.artifact_id
        self._latest_by_name[logical_name] = artifact.artifact_id
        return artifact

    def latest(self, logical_name: str) -> Optional[ArtifactMetadata]:
        artifact_id = self._latest_by_name.get(logical_name)
        if not artifact_id:
            return None
        return self._artifacts[artifact_id]

    def get(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        return self._artifacts.get(artifact_id)

    def read(self, artifact_id: str) -> Optional[bytes]:
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return None
        return self._blob_path(artifact.content_digest).read_bytes()

    def verify(self, artifact_id: str) -> bool:
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return False
        path = self._blob_path(artifact.content_digest)
        if not path.exists():
            return False
        return sha256_digest(path.read_bytes()) == artifact.content_digest

    def blob_count(self) -> int:
        return len(self._blobs)

    def artifact_count(self) -> int:
        return len(self._artifacts)

    def _ensure_blob(self, digest: str, content: bytes) -> BlobRef:
        existing = self._blobs.get(digest)
        if existing:
            return existing

        path = self._blob_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            with os.fdopen(os.open(path, flags, 0o444), "wb") as blob_file:
                blob_file.write(content)
        except FileExistsError:
            if sha256_digest(path.read_bytes()) != digest:
                raise ArtifactDigestMismatchError(
                    logical_name=str(path),
                    claimed_digest=digest,
                    verified_digest=sha256_digest(path.read_bytes()),
                    blob=BlobRef(
                        digest=digest,
                        size=len(content),
                        path=str(path),
                    ),
                )

        ref = BlobRef(digest=digest, size=len(content), path=str(path))
        self._blobs[digest] = ref
        return ref

    def _blob_path(self, digest: str) -> Path:
        return self.root / "blobs" / digest[:2] / digest


def sha256_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
