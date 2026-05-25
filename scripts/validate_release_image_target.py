#!/usr/bin/env python3
"""Validate a release image target before registry login or push."""

import argparse
import json
import os
import sys

from src.release.image_targets import (
    ReleaseImageTarget,
    ReleaseTargetError,
    ReleaseTargetValidator,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image",
        help="Image reference: registry/namespace/image:tag",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Approved registry namespace such as ghcr.io/orchestration-agent",
    )
    parser.add_argument(
        "--allow-env",
        default="AO_RELEASE_ALLOWED_NAMESPACES",
        help="Comma separated allowlist environment variable",
    )
    return parser


def allowed_namespaces(args: argparse.Namespace) -> list[str]:
    from_env = os.environ.get(args.allow_env, "")
    return [*args.allow, *from_env.split(",")]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validator = ReleaseTargetValidator(allowed_namespaces(args))

    try:
        summary = validator.validate_before_push(
            ReleaseImageTarget.parse(args.image),
        )
    except ReleaseTargetError as exc:
        print(f"release image target rejected: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
