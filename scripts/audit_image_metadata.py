#!/usr/bin/env python3
"""Audit runtime image metadata for leaked build-only values."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ALLOWED_LABELS = {
    "org.opencontainers.image.title",
    "org.opencontainers.image.version",
    "org.opencontainers.image.description",
    "org.opencontainers.image.source",
    "org.opencontainers.image.revision",
    "org.opencontainers.image.licenses",
}


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _docker_json_lines(args: list[str]) -> list[dict[str, Any]]:
    output = subprocess.check_output(args, text=True)
    return [
        json.loads(line)
        for line in output.splitlines()
        if line.strip()
    ]


def collect_image_metadata(image: str) -> dict[str, Any]:
    history = _docker_json_lines(
        ["docker", "history", "--no-trunc", "--format", "{{json .}}", image]
    )
    inspect_output = subprocess.check_output(
        ["docker", "inspect", image],
        text=True,
    )
    inspect = json.loads(inspect_output)
    return {"history": history, "inspect": inspect}


def audit_metadata(
    metadata: dict[str, Any],
    forbidden_values: Iterable[str],
    allowed_labels: Iterable[str] = DEFAULT_ALLOWED_LABELS,
) -> list[str]:
    failures: list[str] = []
    forbidden = [value for value in forbidden_values if value]

    for section_name in ("history", "inspect"):
        section_text = _as_text(metadata.get(section_name, []))
        for value in forbidden:
            if value in section_text:
                failures.append(
                    "forbidden build value leaked into image "
                    f"{section_name}: {value}"
                )

    allowed = set(allowed_labels)
    for image in metadata.get("inspect", []):
        labels = image.get("Config", {}).get("Labels") or {}
        for label in labels:
            if label not in allowed:
                failures.append(f"unapproved runtime image label: {label}")

    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when final image metadata leaks build-only values."
        )
    )
    parser.add_argument(
        "image",
        nargs="?",
        help="Image tag or digest to audit",
    )
    parser.add_argument(
        "--forbidden-value",
        action="append",
        default=[],
        help=(
            "Build-only value that must not appear in history "
            "or inspect output."
        ),
    )
    parser.add_argument(
        "--allow-label",
        action="append",
        default=[],
        help="Additional runtime label key allowed in final image metadata.",
    )
    parser.add_argument("--history-file", type=Path)
    parser.add_argument("--inspect-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.history_file or args.inspect_file:
        if not (args.history_file and args.inspect_file):
            print(
                "--history-file and --inspect-file must be provided together",
                file=sys.stderr,
            )
            return 2
        metadata = {
            "history": _load_json(args.history_file),
            "inspect": _load_json(args.inspect_file),
        }
    else:
        if not args.image:
            print(
                "image is required when metadata files are not provided",
                file=sys.stderr,
            )
            return 2
        metadata = collect_image_metadata(args.image)

    failures = audit_metadata(
        metadata,
        args.forbidden_value,
        DEFAULT_ALLOWED_LABELS | set(args.allow_label),
    )
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
