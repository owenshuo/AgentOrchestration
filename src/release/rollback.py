"""Versioned release rollback with paired configuration snapshots."""

from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional


class ReleaseRollbackError(RuntimeError):
    """Raised when a rollback cannot be safely completed."""


@dataclass(frozen=True)
class ReleaseSnapshot:
    version: str
    image_digest: str
    config_digest: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class ReleaseRollbackManager:
    def __init__(
        self,
        restore_image: Callable[[ReleaseSnapshot], object],
        restore_config: Callable[[ReleaseSnapshot], object],
        verify_startup: Callable[[ReleaseSnapshot], bool],
        verify_queue: Callable[[ReleaseSnapshot], bool],
    ):
        self.restore_image = restore_image
        self.restore_config = restore_config
        self.verify_startup = verify_startup
        self.verify_queue = verify_queue
        self._history: List[ReleaseSnapshot] = []
        self._current: Optional[ReleaseSnapshot] = None

    def record_release(
        self,
        version: str,
        image_digest: str,
        config_digest: str,
    ) -> ReleaseSnapshot:
        snapshot = ReleaseSnapshot(
            version=version,
            image_digest=image_digest,
            config_digest=config_digest,
        )
        self._history.append(snapshot)
        self._current = snapshot
        return snapshot

    def current_snapshot(self) -> Optional[ReleaseSnapshot]:
        return self._current

    def rollback_to(self, version: str) -> ReleaseSnapshot:
        target = self._find_snapshot(version)
        previous = self._current

        self.restore_config(target)
        self.restore_image(target)

        if not self.verify_startup(target):
            self._current = previous
            raise ReleaseRollbackError("rollback startup verification failed")
        if not self.verify_queue(target):
            self._current = previous
            raise ReleaseRollbackError("rollback queue verification failed")

        self._current = target
        return target

    def release_history(self) -> List[Dict[str, str]]:
        return [snapshot.to_dict() for snapshot in self._history]

    def _find_snapshot(self, version: str) -> ReleaseSnapshot:
        for snapshot in reversed(self._history):
            if snapshot.version == version:
                return snapshot
        raise ReleaseRollbackError("unknown release version")
