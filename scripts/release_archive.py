"""Build reproducible release archives with normalized text files."""

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


TEXT_EXTENSIONS = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
LINE_ENDING_POLICY = "text files are normalized to LF before hashing"


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    sha256: str
    line_endings: str


def build_release_archive(
    source: Path,
    output: Path,
    include: Iterable[str],
) -> Tuple[str, List[ArchiveEntry]]:
    source = source.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = _collect_entries(source, include)

    with output.open("wb") as raw_file:
        with gzip.GzipFile(
            filename="",
            fileobj=raw_file,
            mode="wb",
            mtime=0,
        ) as gzip_file:
            with tarfile.open(
                fileobj=gzip_file,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                for relative_path, payload, entry in entries:
                    info = _tar_info(relative_path, len(payload))
                    archive.addfile(info, io.BytesIO(payload))

                manifest_payload = _manifest(entries).encode("utf-8")
                manifest = _tar_info(
                    "RELEASE-LINE-ENDINGS.json",
                    len(manifest_payload),
                )
                archive.addfile(manifest, io.BytesIO(manifest_payload))

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return digest, [entry for _, _, entry in entries]


def _collect_entries(
    source: Path,
    include: Iterable[str],
) -> List[Tuple[str, bytes, ArchiveEntry]]:
    collected = []
    for pattern in include:
        for path in sorted(source.glob(pattern)):
            if not path.is_file():
                continue
            relative_path = path.relative_to(source).as_posix()
            payload, line_endings = _normalized_payload(path)
            collected.append(
                (
                    relative_path,
                    payload,
                    ArchiveEntry(
                        path=relative_path,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        line_endings=line_endings,
                    ),
                )
            )
    return collected


def _normalized_payload(path: Path) -> Tuple[bytes, str]:
    payload = path.read_bytes()
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return payload, "binary"
    normalized = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return normalized, "LF"


def _manifest(entries: List[Tuple[str, bytes, ArchiveEntry]]) -> str:
    payload = {
        "line_ending_policy": LINE_ENDING_POLICY,
        "entries": [
            {
                "path": entry.path,
                "sha256": entry.sha256,
                "line_endings": entry.line_endings,
            }
            for _, _, entry in entries
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _tar_info(path: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(path)
    info.size = size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include",
        action="append",
        default=["README.md", "pyproject.toml", "src/**/*.py"],
    )
    args = parser.parse_args()
    digest, _ = build_release_archive(args.source, args.output, args.include)
    print(digest)


if __name__ == "__main__":
    main()
