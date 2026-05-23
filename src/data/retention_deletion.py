"""Retention deletion workflow with derived-store reconciliation."""

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set


@dataclass(frozen=True)
class DeletionManifest:
    workspace_id: str
    artifact_ids: List[str]
    primary_store: str = "artifacts"
    derived_stores: tuple = ("embeddings", "indexes")

    @property
    def all_stores(self) -> List[str]:
        return [self.primary_store, *self.derived_stores]


class InMemoryRetentionStore:
    def __init__(self, name: str):
        self.name = name
        self._records: Dict[str, Dict[str, Any]] = {}

    def put(
        self,
        record_id: str,
        *,
        artifact_id: str,
        workspace_id: str,
    ) -> None:
        self._records[record_id] = {
            "id": record_id,
            "artifact_id": artifact_id,
            "workspace_id": workspace_id,
        }

    def has_artifact(self, workspace_id: str, artifact_id: str) -> bool:
        return any(
            record["workspace_id"] == workspace_id
            and record["artifact_id"] == artifact_id
            for record in self._records.values()
        )

    def delete_artifact(self, workspace_id: str, artifact_id: str) -> int:
        record_ids = [
            record_id
            for record_id, record in self._records.items()
            if record["workspace_id"] == workspace_id
            and record["artifact_id"] == artifact_id
        ]
        for record_id in record_ids:
            self._records.pop(record_id, None)
        return len(record_ids)

    def artifact_ids(self, workspace_id: str) -> Set[str]:
        return {
            record["artifact_id"]
            for record in self._records.values()
            if record["workspace_id"] == workspace_id
        }

    def records(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._records.values()]


class RetentionDeletionWorkflow:
    def __init__(self, stores: Dict[str, InMemoryRetentionStore]):
        self.stores = stores
        self._completion_records: List[Dict[str, Any]] = []

    def build_manifest(
        self,
        workspace_id: str,
        artifact_ids: Iterable[str],
        *,
        primary_store: str = "artifacts",
        derived_stores: Optional[Iterable[str]] = None,
    ) -> DeletionManifest:
        derived = tuple(derived_stores or ("embeddings", "indexes"))
        manifest = DeletionManifest(
            workspace_id=workspace_id,
            artifact_ids=list(dict.fromkeys(artifact_ids)),
            primary_store=primary_store,
            derived_stores=derived,
        )
        self._validate_manifest(manifest)
        return manifest

    def execute(self, manifest: DeletionManifest) -> Dict[str, Any]:
        self._validate_manifest(manifest)
        completions = []
        for store_name in manifest.all_stores:
            store = self.stores[store_name]
            deleted = 0
            for artifact_id in manifest.artifact_ids:
                deleted += store.delete_artifact(
                    manifest.workspace_id,
                    artifact_id,
                )
            completions.append(
                self._record_completion(
                    manifest.workspace_id,
                    store_name,
                    deleted,
                )
            )
        return {
            "workspace_id": manifest.workspace_id,
            "artifact_ids": list(manifest.artifact_ids),
            "stores": completions,
        }

    def reconcile(self, workspace_id: str) -> Dict[str, Any]:
        primary_ids = self.stores["artifacts"].artifact_ids(workspace_id)
        removed = []
        for store_name, store in self.stores.items():
            if store_name == "artifacts":
                continue
            stale_ids = sorted(store.artifact_ids(workspace_id) - primary_ids)
            deleted = 0
            for artifact_id in stale_ids:
                deleted += store.delete_artifact(workspace_id, artifact_id)
            if stale_ids:
                removed.append(
                    self._record_completion(
                        workspace_id,
                        store_name,
                        deleted,
                        reconciled=True,
                        artifact_ids=stale_ids,
                    )
                )
        return {"workspace_id": workspace_id, "removed": removed}

    def completion_records(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._completion_records]

    def _validate_manifest(self, manifest: DeletionManifest) -> None:
        missing = [
            name
            for name in manifest.all_stores
            if name not in self.stores
        ]
        if missing:
            stores = ", ".join(missing)
            raise ValueError(f"unknown retention stores: {stores}")

    def _record_completion(
        self,
        workspace_id: str,
        store_name: str,
        deleted: int,
        *,
        reconciled: bool = False,
        artifact_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        record = {
            "workspace_id": workspace_id,
            "store": store_name,
            "deleted": deleted,
            "completed_at": time.time(),
            "reconciled": reconciled,
        }
        if artifact_ids is not None:
            record["artifact_ids"] = list(artifact_ids)
        self._completion_records.append(record)
        return dict(record)
