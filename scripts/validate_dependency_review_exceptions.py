"""Validate dependency review exception metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

import yaml


REQUIRED_FIELDS = {
    "id",
    "dependency",
    "owner",
    "reason",
    "expires_on",
    "review_url",
}


def load_manifest(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a mapping")
    return data


def validate_manifest(
    manifest: Dict[str, Any],
    *,
    today: dt.date,
) -> List[str]:
    exceptions = manifest.get("exceptions", [])
    if not isinstance(exceptions, list):
        return ["exceptions must be a list"]

    errors: List[str] = []
    seen_ids = set()
    for index, exception in enumerate(exceptions):
        prefix = f"exceptions[{index}]"
        if not isinstance(exception, dict):
            errors.append(f"{prefix} must be a mapping")
            continue

        missing = sorted(REQUIRED_FIELDS - set(exception))
        if missing:
            fields = ", ".join(missing)
            errors.append(f"{prefix} missing required fields: {fields}")

        exception_id = exception.get("id")
        if exception_id in seen_ids:
            errors.append(f"{prefix}.id duplicates {exception_id}")
        elif exception_id:
            seen_ids.add(exception_id)

        for field in REQUIRED_FIELDS - {"expires_on"}:
            value = exception.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")

        expires_on = exception.get("expires_on")
        expires_date = _parse_date(expires_on)
        if expires_date is None:
            errors.append(f"{prefix}.expires_on must use YYYY-MM-DD")
        elif expires_date < today:
            errors.append(
                f"{prefix}.expires_on expired on {expires_date.isoformat()}"
            )

    return errors


def render_summary(manifest: Dict[str, Any]) -> str:
    exceptions = manifest.get("exceptions", [])
    if not exceptions:
        return "No active dependency review exceptions."

    lines = ["Dependency review exceptions:"]
    for exception in exceptions:
        lines.append(
            "- {id}: {dependency} owned by {owner}, expires {expires_on}, "
            "review {review_url}".format(**exception)
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest",
        nargs="?",
        default=".github/dependency-review-exceptions.yml",
    )
    parser.add_argument(
        "--today",
        help="Override current date for deterministic tests (YYYY-MM-DD).",
    )
    args = parser.parse_args(argv)

    today = _parse_date(args.today) if args.today else dt.date.today()
    if today is None:
        print("--today must use YYYY-MM-DD", file=sys.stderr)
        return 2

    manifest = load_manifest(Path(args.manifest))
    errors = validate_manifest(manifest, today=today)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(render_summary(manifest))
    return 0


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
