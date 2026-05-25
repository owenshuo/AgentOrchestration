"""Local artifact download cache with checksum validation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class CacheEntry:
    key: str
    path: Path
    expected_size: int
    expected_digest: str


class ArtifactDownloadCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, CacheEntry] = {}
        self.evictions: list[Dict[str, str]] = []

    def get_or_download(
        self,
        key: str,
        expected_digest: str,
        downloader: Callable[[Path], None],
        expected_size: Optional[int] = None,
    ) -> Path:
        existing = self._entries.get(key) or self._load_entry(key)
        if existing and self._is_valid(existing):
            return existing.path
        if existing:
            self.evict(key, "cache_validation_failed")

        target = self.cache_dir / self._safe_name(key)
        download_target = self._download_path(key)
        self._delete_path(download_target)
        downloader(download_target)
        actual_size = download_target.stat().st_size
        entry = CacheEntry(
            key=key,
            path=download_target,
            expected_size=(
                actual_size if expected_size is None else expected_size
            ),
            expected_digest=expected_digest,
        )
        if not self._is_valid(entry):
            self._delete_path(download_target)
            raise ValueError(f"downloaded artifact failed checksum for {key}")
        download_target.replace(target)
        entry = CacheEntry(
            key=key,
            path=target,
            expected_size=entry.expected_size,
            expected_digest=expected_digest,
        )
        self._record(entry)
        return target

    def add_entry(
        self,
        key: str,
        path: Path,
        expected_digest: str,
        expected_size: Optional[int] = None,
    ) -> None:
        artifact_path = Path(path)
        size = (
            artifact_path.stat().st_size
            if expected_size is None
            else expected_size
        )
        self._record(CacheEntry(
            key=key,
            path=artifact_path,
            expected_size=size,
            expected_digest=expected_digest,
        ))

    def get(self, key: str) -> Optional[Path]:
        entry = self._entries.get(key) or self._load_entry(key)
        if not entry:
            return None
        if not self._is_valid(entry):
            self.evict(key, "cache_validation_failed")
            return None
        return entry.path

    def evict(self, key: str, reason: str) -> None:
        entry = self._entries.pop(key, None)
        if not entry:
            return
        self._delete_path(entry.path)
        self._delete_path(self._metadata_path(key))
        self.evictions.append({"key": key, "reason": reason})

    def _is_valid(self, entry: CacheEntry) -> bool:
        if not entry.path.exists() or not entry.path.is_file():
            return False
        if entry.path.stat().st_size != entry.expected_size:
            return False
        return self._digest(entry.path) == entry.expected_digest

    def _digest(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _record(self, entry: CacheEntry) -> None:
        self._entries[entry.key] = entry
        metadata = {
            "key": entry.key,
            "path": str(entry.path),
            "expected_size": entry.expected_size,
            "expected_digest": entry.expected_digest,
        }
        self._metadata_path(entry.key).write_text(
            json.dumps(metadata, sort_keys=True),
            encoding="utf-8",
        )

    def _load_entry(self, key: str) -> Optional[CacheEntry]:
        metadata_path = self._metadata_path(key)
        if not metadata_path.exists():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("key") != key:
                return None
            return CacheEntry(
                key=key,
                path=Path(metadata["path"]),
                expected_size=int(metadata["expected_size"]),
                expected_digest=str(metadata["expected_digest"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._delete_path(metadata_path)
            return None

    def _safe_name(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _metadata_path(self, key: str) -> Path:
        return self.cache_dir / f"{self._safe_name(key)}.metadata.json"

    def _download_path(self, key: str) -> Path:
        return self.cache_dir / f"{self._safe_name(key)}.download"

    def _delete_path(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
