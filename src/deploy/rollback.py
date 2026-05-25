"""Versioned release manifest and rollback helpers."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Dict, Optional


class RollbackVerificationError(RuntimeError):
    """Raised when rollback verification fails."""


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    image_digest: str
    config_digest: str
    config_snapshot: Dict[str, Any]


def config_digest(config: Dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReleaseRollbackManager:
    def __init__(
        self,
        startup_check: Optional[Callable[[ReleaseManifest], bool]] = None,
        queue_check: Optional[Callable[[ReleaseManifest], bool]] = None,
    ):
        self._manifests: Dict[str, ReleaseManifest] = {}
        self._current_version: Optional[str] = None
        self._current_image_digest: Optional[str] = None
        self._current_config: Dict[str, Any] = {}
        self._startup_check = startup_check or (lambda manifest: True)
        self._queue_check = queue_check or (lambda manifest: True)

    @property
    def current_version(self) -> Optional[str]:
        return self._current_version

    @property
    def current_image_digest(self) -> Optional[str]:
        return self._current_image_digest

    @property
    def current_config(self) -> Dict[str, Any]:
        return deepcopy(self._current_config)

    def record_release(
        self,
        version: str,
        image_digest: str,
        config: Dict[str, Any],
        activate: bool = True,
    ) -> ReleaseManifest:
        snapshot = deepcopy(config)
        manifest = ReleaseManifest(
            version=version,
            image_digest=image_digest,
            config_digest=config_digest(snapshot),
            config_snapshot=snapshot,
        )
        self._manifests[version] = manifest
        if activate:
            self._apply_manifest(manifest)
        return manifest

    def get_manifest(self, version: str) -> Optional[ReleaseManifest]:
        return self._manifests.get(version)

    def rollback_to(self, version: str) -> ReleaseManifest:
        manifest = self._manifests.get(version)
        if manifest is None:
            raise KeyError(f"unknown release version: {version}")

        if config_digest(manifest.config_snapshot) != manifest.config_digest:
            raise RollbackVerificationError(
                f"configuration snapshot digest mismatch for {version}"
            )

        previous_version = self._current_version
        previous_image_digest = self._current_image_digest
        previous_config = deepcopy(self._current_config)

        self._apply_manifest(manifest)
        try:
            self.verify_rollback(manifest)
        except RollbackVerificationError:
            self._current_version = previous_version
            self._current_image_digest = previous_image_digest
            self._current_config = previous_config
            raise

        return manifest

    def verify_rollback(self, manifest: ReleaseManifest) -> None:
        if not self._startup_check(manifest):
            raise RollbackVerificationError(
                f"startup verification failed for {manifest.version}"
            )
        if not self._queue_check(manifest):
            raise RollbackVerificationError(
                "queue connectivity verification failed for "
                f"{manifest.version}"
            )

    def _apply_manifest(self, manifest: ReleaseManifest) -> None:
        self._current_version = manifest.version
        self._current_image_digest = manifest.image_digest
        self._current_config = deepcopy(manifest.config_snapshot)
