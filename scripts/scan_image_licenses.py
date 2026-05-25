#!/usr/bin/env python3
"""Scan final runtime image packages against a license policy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

UNKNOWN = "UNKNOWN"

COLLECT_SCRIPT = r"""
import importlib.metadata as metadata
import json
from pathlib import Path


def system_packages():
    status_path = Path("/var/lib/dpkg/status")
    if not status_path.exists():
        return []

    packages = []
    current = {}
    for line in status_path.read_text(errors="replace").splitlines():
        if not line:
            if current.get("Package"):
                packages.append(
                    {
                        "ecosystem": "system",
                        "name": current["Package"],
                        "version": current.get("Version", ""),
                        "license": current.get("License", "UNKNOWN"),
                    }
                )
            current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key] = value.strip()

    if current.get("Package"):
        packages.append(
            {
                "ecosystem": "system",
                "name": current["Package"],
                "version": current.get("Version", ""),
                "license": current.get("License", "UNKNOWN"),
            }
        )
    return packages


def python_packages():
    packages = []
    for dist in metadata.distributions():
        meta = dist.metadata
        license_name = meta.get("License") or "UNKNOWN"
        if license_name == "UNKNOWN":
            for classifier in meta.get_all("Classifier", []):
                prefix = "License :: OSI Approved :: "
                if classifier.startswith(prefix):
                    license_name = classifier.removeprefix(prefix)
                    break
        packages.append(
            {
                "ecosystem": "python",
                "name": meta.get("Name", dist.metadata["Name"]),
                "version": meta.get("Version", dist.version),
                "license": license_name,
            }
        )
    return packages


print(json.dumps({"packages": system_packages() + python_packages()}))
"""


def load_policy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def normalize_license(value: str | None) -> str:
    if not value:
        return UNKNOWN
    normalized = " ".join(value.replace("\n", " ").split())
    return normalized or UNKNOWN


def exception_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("ecosystem", "")),
        str(entry.get("package", "")),
        normalize_license(entry.get("license")),
    )


def validate_exception(entry: dict[str, Any], today: dt.date) -> str | None:
    if not entry.get("owner"):
        return "missing owner"
    if not entry.get("expires"):
        return "missing expiration"
    try:
        expires = dt.date.fromisoformat(str(entry["expires"]))
    except ValueError:
        return "invalid expiration"
    if expires < today:
        return f"expired on {expires.isoformat()}"
    if not entry.get("reason"):
        return "missing reason"
    return None


def build_exception_map(
    policy: dict[str, Any],
    today: dt.date,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[str]]:
    exceptions = {}
    errors = []
    for entry in policy.get("exceptions", []):
        problem = validate_exception(entry, today)
        key = exception_key(entry)
        if problem:
            message = (
                f"invalid exception for {key[0]}:{key[1]} "
                f"({key[2]}): {problem}"
            )
            errors.append(message)
            continue
        exceptions[key] = entry
    return exceptions, errors


def package_key(package: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(package.get("ecosystem", "")),
        str(package.get("name", "")),
        normalize_license(package.get("license")),
    )


def evaluate_report(
    report: dict[str, Any],
    policy: dict[str, Any],
    today: dt.date | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    today = today or dt.date.today()
    allowed = {
        normalize_license(item)
        for item in policy.get("allow_licenses", [])
    }
    prohibited = {
        normalize_license(item)
        for item in policy.get("prohibited_licenses", [])
    }
    deny_unknown = bool(policy.get("deny_unknown", False))
    exceptions, errors = build_exception_map(policy, today)
    violations = list(errors)
    packages = report.get("packages", [])

    for package in packages:
        license_name = normalize_license(package.get("license"))
        key = package_key(package)
        if key in exceptions:
            package["exception"] = exceptions[key]
            continue
        if license_name in prohibited:
            prefix = f"{package['ecosystem']}:{package['name']}"
            violations.append(
                f"{prefix} {package.get('version', '')} "
                f"uses prohibited license {license_name}"
            )
        elif deny_unknown and license_name not in allowed:
            prefix = f"{package['ecosystem']}:{package['name']}"
            violations.append(
                f"{prefix} {package.get('version', '')} "
                f"has unapproved license {license_name}"
            )

    return violations, packages


def collect_image_report(image: str) -> dict[str, Any]:
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        image,
        "-c",
        COLLECT_SCRIPT,
    ]
    output = subprocess.check_output(command, text=True)
    return json.loads(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a runtime Docker image for license policy violations."
        )
    )
    parser.add_argument("image", nargs="?")
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("infra/license_policy.json"),
    )
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.report_json:
        report = json.loads(args.report_json.read_text())
    elif args.image:
        report = collect_image_report(args.image)
    else:
        print("image or --report-json is required", file=sys.stderr)
        return 2

    policy = load_policy(args.policy)
    violations, packages = evaluate_report(report, policy)
    report["packages"] = packages

    if args.output:
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )

    system_count = sum(
        1 for package in packages if package.get("ecosystem") == "system"
    )
    python_count = sum(
        1 for package in packages if package.get("ecosystem") == "python"
    )
    print(
        f"scanned {len(packages)} runtime packages "
        f"({system_count} system, {python_count} python)"
    )
    if violations:
        print("license policy violations:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
