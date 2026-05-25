#!/usr/bin/env python3
"""Verify runtime images expose deterministic UTC timezone behavior."""

import argparse
import json
import subprocess
import sys
from typing import Any

RUNTIME_CHECK = """
import datetime as dt
import json
import os
import time

now = dt.datetime.now().astimezone()
print(json.dumps({
    "TZ": os.environ.get("TZ"),
    "time_tzname": list(time.tzname),
    "timezone_offset": time.timezone,
    "local_utc_offset": int(now.utcoffset().total_seconds()),
}))
"""


def image_env(image: str) -> dict[str, str]:
    output = subprocess.check_output(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            "{{json .Config.Env}}",
        ],
        text=True,
    )
    values = json.loads(output)
    return dict(item.split("=", 1) for item in values if "=" in item)


def runtime_timezone(image: str) -> dict[str, Any]:
    output = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image,
            "-c",
            RUNTIME_CHECK,
        ],
        text=True,
    )
    return json.loads(output)


def validate_timezone(
    env: dict[str, str],
    runtime: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if env.get("TZ") != "UTC":
        errors.append("image Config.Env must include TZ=UTC")
    if runtime.get("TZ") != "UTC":
        errors.append("container runtime must expose TZ=UTC")
    if runtime.get("local_utc_offset") != 0:
        errors.append("container local timezone offset must be zero seconds")
    if "UTC" not in runtime.get("time_tzname", []):
        errors.append("container time.tzname must include UTC")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a runtime image for UTC timezone configuration."
    )
    parser.add_argument("image", nargs="?")
    parser.add_argument("--env-json")
    parser.add_argument("--runtime-json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_json and args.runtime_json:
        env = json.loads(args.env_json)
        runtime = json.loads(args.runtime_json)
    elif args.image:
        env = image_env(args.image)
        runtime = runtime_timezone(args.image)
    else:
        print(
            "image or --env-json/--runtime-json is required",
            file=sys.stderr,
        )
        return 2

    errors = validate_timezone(env, runtime)
    if errors:
        print("runtime image timezone inspection failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("runtime image timezone is pinned to UTC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
