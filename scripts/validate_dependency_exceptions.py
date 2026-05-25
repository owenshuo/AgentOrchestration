"""Validate tracked dependency-review exception decisions."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_MANIFEST = Path(".github/dependency-review-exceptions.json")
REQUIRED_EXCEPTION_FIELDS = ("id", "owner", "reason", "expires")
REQUIRED_DEPENDENCY_FIELDS = ("ecosystem", "name", "version")


@dataclass(frozen=True)
class DependencyException:
    identifier: str
    owner: str
    reason: str
    expires: date
    dependency: Dict[str, str]
    active: bool
    manifest_path: Path

    @property
    def coordinates(self) -> Tuple[str, str, str]:
        return (
            self.dependency["ecosystem"],
            self.dependency["name"],
            self.dependency["version"],
        )

    def summary_row(self) -> str:
        return (
            f"| `{self.identifier}` | `{self.coordinates[0]}` | "
            f"`{self.coordinates[1]}` | `{self.coordinates[2]}` | "
            f"{self.owner} | {self.expires.isoformat()} | "
            f"[manifest]({self.manifest_path.as_posix()}) |"
        )


class ValidationError(Exception):
    """Raised when dependency exception metadata is invalid."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--today", type=date.fromisoformat)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ValidationError(f"{path} is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc


def load_exceptions(path: Path) -> List[DependencyException]:
    payload = load_json(path)
    raw_exceptions = (
        payload.get("exceptions") if isinstance(payload, dict) else None
    )
    if raw_exceptions is None:
        raise ValidationError(f"{path} must contain an exceptions list")
    if not isinstance(raw_exceptions, list):
        raise ValidationError(f"{path} exceptions must be a list")

    exceptions: List[DependencyException] = []
    seen_ids = set()
    for index, entry in enumerate(raw_exceptions):
        if not isinstance(entry, dict):
            raise ValidationError(f"exceptions[{index}] must be an object")
        missing = [
            field
            for field in REQUIRED_EXCEPTION_FIELDS
            if not entry.get(field)
        ]
        if missing:
            raise ValidationError(
                f"exceptions[{index}] missing required field(s): "
                f"{', '.join(missing)}"
            )
        identifier = str(entry["id"])
        if identifier in seen_ids:
            raise ValidationError(f"duplicate exception id: {identifier}")
        seen_ids.add(identifier)

        dependency = entry.get("dependency")
        if not isinstance(dependency, dict):
            raise ValidationError(
                f"exceptions[{index}] dependency must be an object"
            )
        missing_dependency = [
            field
            for field in REQUIRED_DEPENDENCY_FIELDS
            if not dependency.get(field)
        ]
        if missing_dependency:
            raise ValidationError(
                f"exceptions[{index}] dependency missing field(s): "
                f"{', '.join(missing_dependency)}"
            )
        expires = parse_expiration(str(entry["expires"]), index)
        exceptions.append(
            DependencyException(
                identifier=identifier,
                owner=str(entry["owner"]),
                reason=str(entry["reason"]),
                expires=expires,
                dependency={
                    field: str(dependency[field])
                    for field in REQUIRED_DEPENDENCY_FIELDS
                },
                active=bool(entry.get("active", True)),
                manifest_path=path,
            )
        )
    return exceptions


def parse_expiration(value: str, index: int) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(
            f"exceptions[{index}] expires must use YYYY-MM-DD"
        ) from exc


def validate_expiration(
    exceptions: Iterable[DependencyException],
    today: date,
) -> None:
    expired = [
        item for item in exceptions if item.active and item.expires < today
    ]
    if expired:
        details = ", ".join(item.identifier for item in expired)
        raise ValidationError(
            f"expired dependency exception(s) must be removed or renewed: "
            f"{details}"
        )


def load_overrides(path: Optional[Path]) -> List[Dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = load_json(path)
    if isinstance(payload, dict):
        raw_overrides = payload.get("overrides", [])
    else:
        raw_overrides = payload
    if not isinstance(raw_overrides, list):
        raise ValidationError(f"{path} overrides must be a list")
    for index, override in enumerate(raw_overrides):
        if not isinstance(override, dict):
            raise ValidationError(f"overrides[{index}] must be an object")
    return raw_overrides


def validate_overrides(
    exceptions: Iterable[DependencyException],
    overrides: Iterable[Dict[str, Any]],
) -> None:
    exceptions_by_id = {
        item.identifier: item for item in exceptions if item.active
    }
    exceptions_by_coordinates = {
        item.coordinates: item for item in exceptions if item.active
    }
    unmatched = []
    for override in overrides:
        identifier = override.get("id") or override.get("exception_id")
        dependency = override.get("dependency", {})
        coordinates = (
            str(dependency.get("ecosystem", "")),
            str(dependency.get("name", "")),
            str(dependency.get("version", "")),
        )
        if identifier and identifier in exceptions_by_id:
            continue
        if coordinates in exceptions_by_coordinates:
            continue
        unmatched.append(identifier or ":".join(coordinates))
    if unmatched:
        raise ValidationError(
            "dependency review override(s) missing tracked manifest entry: "
            + ", ".join(unmatched)
        )


def write_summary(
    path: Optional[Path],
    exceptions: Iterable[DependencyException],
) -> None:
    if path is None:
        return
    active = [item for item in exceptions if item.active]
    lines = [
        "## Dependency Review Exceptions",
        "",
        "Tracked exception records validated by CI.",
        "",
    ]
    if active:
        lines.extend(
            [
                "| ID | Ecosystem | Name | Version | Owner | Expires | "
                "Record |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(item.summary_row() for item in active)
    else:
        lines.append("No active dependency review exceptions.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate(
    manifest: Path,
    overrides: Optional[Path],
    today: Optional[date] = None,
) -> List[DependencyException]:
    exceptions = load_exceptions(manifest)
    validate_expiration(exceptions, today or date.today())
    validate_overrides(exceptions, load_overrides(overrides))
    return exceptions


def main() -> int:
    args = parse_args()
    try:
        exceptions = validate(args.manifest, args.overrides, args.today)
        write_summary(args.summary, exceptions)
    except ValidationError as exc:
        print(f"dependency exception validation failed: {exc}")
        return 1
    print("dependency exception manifest is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
