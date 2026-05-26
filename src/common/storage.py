"""Artifact storage with retention-aware derived search indexes."""

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Dict, List, Optional, Set


@dataclass
class ArtifactRecord:
    artifact_id: str
    payload: Any
    created_at: float
    retention_seconds: Optional[float] = None
    derived_index_ids: Set[str] = field(default_factory=set)


@dataclass
class DerivedIndexRecord:
    index_id: str
    artifact_id: str
    metadata: Dict[str, Any]
    created_at: float


class ArtifactIndexStore:
    """Stores artifacts and cascades retention cleanup to derived indexes."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._artifacts: Dict[str, ArtifactRecord] = {}
        self._derived_indexes: Dict[str, DerivedIndexRecord] = {}

    def put_artifact(
        self,
        artifact_id: str,
        payload: Any,
        retention_seconds: Optional[float] = None,
    ) -> None:
        if retention_seconds is not None and retention_seconds < 0:
            raise ValueError("retention_seconds must be non-negative")

        existing = self._artifacts.get(artifact_id)
        derived_index_ids = (
            set(existing.derived_index_ids)
            if existing
            else set()
        )
        self._artifacts[artifact_id] = ArtifactRecord(
            artifact_id=artifact_id,
            payload=payload,
            created_at=self._clock(),
            retention_seconds=retention_seconds,
            derived_index_ids=derived_index_ids,
        )

    def get_artifact(self, artifact_id: str) -> Optional[Any]:
        record = self._artifacts.get(artifact_id)
        if not record:
            return None
        if self._is_expired(record):
            self.delete_artifact(artifact_id)
            return None
        return record.payload

    def put_derived_index(
        self,
        index_id: str,
        artifact_id: str,
        metadata: Dict[str, Any],
    ) -> None:
        if artifact_id not in self._artifacts:
            raise KeyError("artifact must exist before indexing")

        existing = self._derived_indexes.get(index_id)
        if existing and existing.artifact_id in self._artifacts:
            self._artifacts[existing.artifact_id].derived_index_ids.discard(
                index_id,
            )

        self._derived_indexes[index_id] = DerivedIndexRecord(
            index_id=index_id,
            artifact_id=artifact_id,
            metadata=dict(metadata),
            created_at=self._clock(),
        )
        self._artifacts[artifact_id].derived_index_ids.add(index_id)

    def get_derived_index(self, index_id: str) -> Optional[Dict[str, Any]]:
        record = self._derived_indexes.get(index_id)
        if not record:
            return None
        if record.artifact_id not in self._artifacts:
            return None
        return dict(record.metadata)

    def delete_artifact(self, artifact_id: str) -> bool:
        record = self._artifacts.pop(artifact_id, None)
        if not record:
            return False

        for index_id in list(record.derived_index_ids):
            self._derived_indexes.pop(index_id, None)
        return True

    def reconcile_retention(self) -> Dict[str, List[str]]:
        """Remove expired artifacts and orphaned derived indexes."""
        report = self.retention_report()
        expired_artifacts = list(report["expired_artifacts"])
        stale_derived_indexes = list(report["stale_derived_indexes"])

        for artifact_id in expired_artifacts:
            self.delete_artifact(artifact_id)

        for index_id in stale_derived_indexes:
            self._derived_indexes.pop(index_id, None)

        return {
            "expired_artifacts": expired_artifacts,
            "stale_derived_indexes": stale_derived_indexes,
        }

    def retention_report(self) -> Dict[str, Any]:
        """Preview retention cleanup without exposing stored payloads."""
        expired_artifacts = [
            artifact_id
            for artifact_id, record in self._artifacts.items()
            if self._is_expired(record)
        ]
        stale_derived_indexes = [
            index_id
            for index_id, record in self._derived_indexes.items()
            if record.artifact_id not in self._artifacts
        ]

        expired_artifacts.sort()
        stale_derived_indexes.sort()
        return {
            "expired_artifacts": expired_artifacts,
            "stale_derived_indexes": stale_derived_indexes,
            "counts": {
                "artifacts": len(self._artifacts),
                "derived_indexes": len(self._derived_indexes),
                "expired_artifacts": len(expired_artifacts),
                "stale_derived_indexes": len(stale_derived_indexes),
            },
        }

    def artifact_ids(self) -> List[str]:
        return sorted(self._artifacts)

    def derived_index_ids(self) -> List[str]:
        return sorted(self._derived_indexes)

    def _is_expired(self, record: ArtifactRecord) -> bool:
        if record.retention_seconds is None:
            return False
        return self._clock() - record.created_at >= record.retention_seconds
