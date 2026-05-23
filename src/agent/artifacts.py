"""Artifact reads with cross-region replication consistency guards."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Iterable, Optional, Protocol, Tuple

from src.common.errors import ArtifactConsistencyError, ArtifactNotFoundError


class ArtifactReplicationState(Enum):
    """Metadata state used to decide whether a miss can still be transient."""

    AVAILABLE = "available"
    PENDING = "pending"
    MISSING = "missing"


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: str
    origin_region: str
    digest: str
    size: int
    created_at: float
    regions: Dict[str, ArtifactReplicationState]

    def state_for(self, region: str) -> ArtifactReplicationState:
        return self.regions.get(region, ArtifactReplicationState.MISSING)


@dataclass(frozen=True)
class ArtifactReadResult:
    artifact_id: str
    region: str
    data: bytes
    digest: str
    attempts: int


class ArtifactStore(Protocol):
    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Return digest and replication metadata for an artifact."""

    def read_bytes(self, artifact_id: str, region: str) -> Optional[bytes]:
        """Return bytes from a region or None when absent."""


class InMemoryArtifactStore:
    """Small store useful for tests and local integrations."""

    def __init__(self, now: Callable[[], float] = time.monotonic):
        self._now = now
        self._metadata: Dict[str, ArtifactMetadata] = {}
        self._objects: Dict[Tuple[str, str], bytes] = {}

    def put(
        self,
        artifact_id: str,
        data: bytes,
        origin_region: str,
        replica_regions: Iterable[str] = (),
    ) -> ArtifactMetadata:
        digest = _sha256(data)
        regions = {origin_region: ArtifactReplicationState.AVAILABLE}
        regions.update({
            region: ArtifactReplicationState.PENDING
            for region in replica_regions
        })
        metadata = ArtifactMetadata(
            artifact_id=artifact_id,
            origin_region=origin_region,
            digest=digest,
            size=len(data),
            created_at=self._now(),
            regions=regions,
        )
        self._metadata[artifact_id] = metadata
        self._objects[(artifact_id, origin_region)] = data
        return metadata

    def mark_available(
        self, artifact_id: str, region: str, data: bytes
    ) -> None:
        metadata = self._metadata[artifact_id]
        regions = dict(metadata.regions)
        regions[region] = ArtifactReplicationState.AVAILABLE
        self._metadata[artifact_id] = ArtifactMetadata(
            artifact_id=metadata.artifact_id,
            origin_region=metadata.origin_region,
            digest=metadata.digest,
            size=metadata.size,
            created_at=metadata.created_at,
            regions=regions,
        )
        self._objects[(artifact_id, region)] = data

    def mark_missing(self, artifact_id: str, region: str) -> None:
        metadata = self._metadata[artifact_id]
        regions = dict(metadata.regions)
        regions[region] = ArtifactReplicationState.MISSING
        self._metadata[artifact_id] = ArtifactMetadata(
            artifact_id=metadata.artifact_id,
            origin_region=metadata.origin_region,
            digest=metadata.digest,
            size=metadata.size,
            created_at=metadata.created_at,
            regions=regions,
        )
        self._objects.pop((artifact_id, region), None)

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        return self._metadata.get(artifact_id)

    def read_bytes(self, artifact_id: str, region: str) -> Optional[bytes]:
        return self._objects.get((artifact_id, region))


class CrossRegionArtifactReader:
    """Read replicated artifacts without treating replication lag as loss."""

    def __init__(
        self,
        store: ArtifactStore,
        replication_window_seconds: float = 300,
        retry_delays: Iterable[float] = (0.25, 0.5, 1.0, 2.0),
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.store = store
        self.replication_window_seconds = replication_window_seconds
        self.retry_delays = tuple(retry_delays)
        self._now = now
        self._sleep = sleep

    def read(self, artifact_id: str, region: str) -> ArtifactReadResult:
        metadata = self.store.get_metadata(artifact_id)
        if metadata is None:
            raise ArtifactNotFoundError(
                artifact_id=artifact_id,
                region=region,
                metadata_state=ArtifactReplicationState.MISSING.value,
            )

        attempts = 0
        while True:
            attempts += 1
            state = metadata.state_for(region)
            data = self.store.read_bytes(artifact_id, region)
            is_available = state == ArtifactReplicationState.AVAILABLE
            if is_available and data is not None:
                self._verify_digest(metadata, data, region)
                return ArtifactReadResult(
                    artifact_id=artifact_id,
                    region=region,
                    data=data,
                    digest=metadata.digest,
                    attempts=attempts,
                )

            if state == ArtifactReplicationState.MISSING:
                raise ArtifactNotFoundError(
                    artifact_id=artifact_id,
                    region=region,
                    metadata_state=state.value,
                    origin_region=metadata.origin_region,
                )

            if not self._should_retry(metadata):
                raise ArtifactNotFoundError(
                    artifact_id=artifact_id,
                    region=region,
                    metadata_state=state.value,
                    origin_region=metadata.origin_region,
                    replication_age_seconds=self._replication_age(metadata),
                )

            delay = self._next_delay(attempts)
            if delay is None:
                raise ArtifactNotFoundError(
                    artifact_id=artifact_id,
                    region=region,
                    metadata_state=state.value,
                    origin_region=metadata.origin_region,
                    replication_age_seconds=self._replication_age(metadata),
                )
            self._sleep(delay)
            metadata = self.store.get_metadata(artifact_id) or metadata

    def _verify_digest(
        self, metadata: ArtifactMetadata, data: bytes, region: str
    ) -> None:
        actual_digest = _sha256(data)
        if actual_digest != metadata.digest or len(data) != metadata.size:
            raise ArtifactConsistencyError(
                artifact_id=metadata.artifact_id,
                region=region,
                expected_digest=metadata.digest,
                actual_digest=actual_digest,
            )

    def _should_retry(self, metadata: ArtifactMetadata) -> bool:
        return (
            self._replication_age(metadata)
            <= self.replication_window_seconds
        )

    def _replication_age(self, metadata: ArtifactMetadata) -> float:
        return self._now() - metadata.created_at

    def _next_delay(self, attempts: int) -> Optional[float]:
        index = attempts - 1
        if index >= len(self.retry_delays):
            return None
        return self.retry_delays[index]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
