#!/usr/bin/env python3
"""Fail release validation when internal workspace dependency ranges drift.

The check discovers local package manifests and changed packages. It then
verifies every package depending on changed internal packages has a range that
accepts the changed package's current version.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


@dataclass(frozen=True)
class WorkspacePackage:
    name: str
    version: str
    root: Path
    manifest: Path
    dependencies: Dict[str, str]


@dataclass(frozen=True)
class DriftFinding:
    dependent: str
    dependency: str
    declared_range: str
    dependency_version: str
    dependent_manifest: Path


def _walk_manifest_paths(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.name in {"pyproject.toml", "package.json"}:
            yield path


def _read_pyproject(path: Path) -> Optional[WorkspacePackage]:
    text = path.read_text(encoding="utf-8")
    project = _extract_pyproject_project_table(text)
    name = project.get("name")
    version = project.get("version")
    if not name or not version:
        return None

    dependencies: Dict[str, str] = {}
    for raw_dep in project.get("dependencies", []):
        dep_name, specifier = _split_python_dependency(raw_dep)
        if dep_name:
            dependencies[dep_name] = specifier

    return WorkspacePackage(
        name=name,
        version=version,
        root=path.parent,
        manifest=path,
        dependencies=dependencies,
    )


def _extract_pyproject_project_table(text: str) -> Dict[str, object]:
    in_project = False
    project: Dict[str, object] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            index += 1
            continue
        if not in_project or not line or line.startswith("#"):
            index += 1
            continue

        if line.startswith("name"):
            match = re.search(r'=\s*["\']([^"\']+)["\']', line)
            if match:
                project["name"] = match.group(1)
        elif line.startswith("version"):
            match = re.search(r'=\s*["\']([^"\']+)["\']', line)
            if match:
                project["version"] = match.group(1)
        elif line.startswith("dependencies"):
            block = line
            while "]" not in block and index + 1 < len(lines):
                index += 1
                block += "\n" + lines[index]
            project["dependencies"] = re.findall(r'["\']([^"\']+)["\']', block)
        index += 1
    return project


def _read_package_json(path: Path) -> Optional[WorkspacePackage]:
    data = json.loads(path.read_text(encoding="utf-8"))
    name = data.get("name")
    version = data.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        return None

    dependencies: Dict[str, str] = {}
    dependency_fields = (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    )
    for field in dependency_fields:
        value = data.get(field, {})
        if isinstance(value, dict):
            dependencies.update({str(k): str(v) for k, v in value.items()})

    return WorkspacePackage(
        name=name,
        version=version,
        root=path.parent,
        manifest=path,
        dependencies=dependencies,
    )


def discover_packages(root: Path) -> List[WorkspacePackage]:
    packages: List[WorkspacePackage] = []
    seen_roots = set()
    for manifest in sorted(_walk_manifest_paths(root)):
        if manifest.parent in seen_roots:
            continue
        package = (
            _read_package_json(manifest)
            if manifest.name == "package.json"
            else _read_pyproject(manifest)
        )
        if package:
            packages.append(package)
            seen_roots.add(manifest.parent)
    return packages


def changed_package_names(
    root: Path,
    packages: Sequence[WorkspacePackage],
    base_ref: str,
    explicit: Sequence[str],
) -> List[str]:
    if explicit:
        return sorted(set(explicit))

    changed_paths = _git_changed_paths(root, base_ref)
    changed = set()
    for path in changed_paths:
        absolute = (root / path).resolve()
        for package in packages:
            try:
                absolute.relative_to(package.root.resolve())
            except ValueError:
                continue
            changed.add(package.name)
    return sorted(changed)


def _git_changed_paths(root: Path, base_ref: str) -> List[Path]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=str(root),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def find_version_drift(
    packages: Sequence[WorkspacePackage], changed_names: Sequence[str]
) -> List[DriftFinding]:
    by_name = {package.name: package for package in packages}
    changed = {name for name in changed_names if name in by_name}
    findings: List[DriftFinding] = []

    for dependent in packages:
        for dependency_name, declared_range in dependent.dependencies.items():
            if dependency_name not in changed:
                continue
            dependency = by_name[dependency_name]
            if not version_satisfies(dependency.version, declared_range):
                findings.append(
                    DriftFinding(
                        dependent=dependent.name,
                        dependency=dependency.name,
                        declared_range=declared_range,
                        dependency_version=dependency.version,
                        dependent_manifest=dependent.manifest,
                    )
                )
    return findings


def _split_python_dependency(raw: str) -> Tuple[str, str]:
    normalized = raw.split(";", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)", normalized)
    if not match:
        return "", ""
    return match.group(1), match.group(2).strip()


def version_satisfies(version: str, specifier: str) -> bool:
    specifier = specifier.strip()
    if not specifier or specifier in {"*", "latest"}:
        return True
    if specifier.startswith(("workspace:", "npm:")):
        specifier = specifier.split(":", 1)[1].strip()
        if specifier in {"", "*"}:
            return True
    if specifier.startswith(("file:", "link:", "path:")):
        return True
    return any(
        _satisfies_all(version, option.strip())
        for option in specifier.split("||")
        if option.strip()
    )


def _satisfies_all(version: str, specifier: str) -> bool:
    constraints = [
        part.strip() for part in specifier.split(",") if part.strip()
    ]
    if not constraints:
        constraints = specifier.split()
    if not constraints:
        return True
    return all(
        _satisfies_one(version, constraint) for constraint in constraints
    )


def _satisfies_one(version: str, constraint: str) -> bool:
    constraint = constraint.strip()
    if constraint in {"*", "latest"}:
        return True
    if constraint.startswith("^"):
        floor = constraint[1:].strip()
        return (
            _compare(version, floor) >= 0
            and _compare(version, _caret_ceiling(floor)) < 0
        )
    if constraint.startswith("~="):
        floor = constraint[2:].strip()
        return (
            _compare(version, floor) >= 0
            and _compare(version, _python_compatible_ceiling(floor)) < 0
        )
    if constraint.startswith("~"):
        floor = constraint[1:].strip()
        return (
            _compare(version, floor) >= 0
            and _compare(version, _tilde_ceiling(floor)) < 0
        )

    match = re.match(r"(===|==|>=|<=|>|<|=)?\s*(.+)", constraint)
    if not match:
        return True
    operator = match.group(1) or "="
    target = match.group(2).strip()
    comparison = _compare(version, target)
    if operator in {"=", "==", "==="}:
        return comparison == 0
    if operator == ">=":
        return comparison >= 0
    if operator == "<=":
        return comparison <= 0
    if operator == ">":
        return comparison > 0
    if operator == "<":
        return comparison < 0
    return True


def _parse_version(version: str) -> Tuple[int, int, int, Tuple[str, ...]]:
    cleaned = version.strip().lstrip("v")
    main, *suffix = re.split(r"[-+]", cleaned, maxsplit=1)
    parts = [
        int(part) if part.isdigit() else 0
        for part in main.split(".")[:3]
    ]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2], tuple(suffix)


def _compare(left: str, right: str) -> int:
    left_v = _parse_version(left)
    right_v = _parse_version(right)
    return (left_v > right_v) - (left_v < right_v)


def _caret_ceiling(version: str) -> str:
    major, minor, patch, _ = _parse_version(version)
    if major > 0:
        return f"{major + 1}.0.0"
    if minor > 0:
        return f"0.{minor + 1}.0"
    return f"0.0.{patch + 1}"


def _tilde_ceiling(version: str) -> str:
    major, minor, _patch, _ = _parse_version(version)
    return f"{major}.{minor + 1}.0"


def _python_compatible_ceiling(version: str) -> str:
    numeric_parts = version.strip().lstrip("v").split("-", 1)[0].split(".")
    major, minor, patch, _ = _parse_version(version)
    if len(numeric_parts) <= 2:
        return f"{major + 1}.0.0"
    return f"{major}.{minor + 1}.0"


def format_findings(findings: Sequence[DriftFinding], root: Path) -> str:
    lines = [
        "Workspace package version drift detected:",
        "",
    ]
    for finding in findings:
        manifest = finding.dependent_manifest.relative_to(root)
        lines.append(
            "- "
            f"{finding.dependent} depends on {finding.dependency} "
            f"with range '{finding.declared_range}', but "
            f"{finding.dependency} is now {finding.dependency_version} "
            f"({manifest})"
        )
    lines.extend(
        [
            "",
            "Update the dependent internal package range before publishing.",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument(
        "--changed-package",
        action="append",
        default=[],
        help="Package name to treat as changed; may be passed more than once.",
    )
    args = parser.parse_args(argv)

    root = Path(args.workspace_root).resolve()
    packages = discover_packages(root)
    changed_names = changed_package_names(
        root, packages, args.base_ref, args.changed_package
    )
    findings = find_version_drift(packages, changed_names)
    if findings:
        print(format_findings(findings, root), file=sys.stderr)
        return 1
    print("Workspace package version policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
