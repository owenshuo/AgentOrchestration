#!/usr/bin/env python3
"""Fail when runtime images contain dependency cache directories."""

import argparse
import json
import subprocess
import sys
from pathlib import PurePosixPath

CACHE_DIR_NAMES = {
    ".cache",
    "pip-cache",
    ".npm",
    ".yarn",
    ".pnpm-store",
    "uv-cache",
}


def find_cache_paths(paths: list[str]) -> list[str]:
    matches: list[str] = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if any(part in CACHE_DIR_NAMES for part in parts):
            matches.append(path)
    return sorted(set(matches))


def list_image_paths(image: str) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        image,
        "-c",
        (
            "import json, os; "
            "print(json.dumps([os.path.join(root, name) "
            "for root, dirs, files in os.walk('/') "
            "for name in dirs + files]))"
        ),
    ]
    output = subprocess.check_output(command, text=True)
    return json.loads(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a runtime image for dependency cache directories."
    )
    parser.add_argument("image", nargs="?")
    parser.add_argument(
        "--paths-json",
        help="JSON array of paths for deterministic tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.paths_json:
        paths = json.loads(args.paths_json)
    elif args.image:
        paths = list_image_paths(args.image)
    else:
        print("image or --paths-json is required", file=sys.stderr)
        return 2

    matches = find_cache_paths(paths)
    if matches:
        print(
            "runtime image contains dependency cache paths:",
            file=sys.stderr,
        )
        for path in matches:
            print(path, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
