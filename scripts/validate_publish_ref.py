#!/usr/bin/env python3
"""Validate package publishing is running from an approved release ref."""

import argparse
import os
import re
import subprocess
import sys

RELEASE_BRANCHES = {"main", "release"}
RELEASE_TAG = re.compile(r"^refs/tags/v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def is_release_tag(ref: str) -> bool:
    return bool(RELEASE_TAG.match(ref))


def is_protected_publish_ref(
    ref: str,
    ref_protected: str,
    event_name: str,
    tag_signed: bool = False,
) -> bool:
    if is_release_tag(ref):
        return tag_signed

    if event_name not in {"push", "workflow_dispatch"}:
        return False

    branch_prefix = "refs/heads/"
    if not ref.startswith(branch_prefix):
        return False

    branch = ref[len(branch_prefix):]
    return branch in RELEASE_BRANCHES and ref_protected.lower() == "true"


def verify_tag_signature(ref: str) -> bool:
    tag = ref.removeprefix("refs/tags/")
    completed = subprocess.run(
        ["git", "verify-tag", tag],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail before registry authentication on unsafe refs."
    )
    parser.add_argument("--ref", default=os.getenv("GITHUB_REF", ""))
    parser.add_argument(
        "--ref-protected",
        default=os.getenv("GITHUB_REF_PROTECTED", "false"),
    )
    parser.add_argument("--event", default=os.getenv("GITHUB_EVENT_NAME", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tag_signed = (
        verify_tag_signature(args.ref)
        if is_release_tag(args.ref)
        else False
    )
    if is_protected_publish_ref(
        args.ref,
        args.ref_protected,
        args.event,
        tag_signed=tag_signed,
    ):
        print(f"publish ref accepted: {args.ref}")
        return 0

    print(
        "ref is not eligible for package publishing before registry auth: "
        f"ref={args.ref!r} protected={args.ref_protected!r} "
        f"event={args.event!r}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
