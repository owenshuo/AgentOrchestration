import json

from scripts.check_workspace_version_drift import (
    discover_packages,
    find_version_drift,
    main,
    version_satisfies,
)


def write_pyproject(path, name, version, dependencies=()):
    deps = "\n".join(f'    "{dep}",' for dep in dependencies)
    path.mkdir(parents=True, exist_ok=True)
    content = (
        f'[project]\n'
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        f'dependencies = [\n{deps}\n]\n'
    )
    (path / "pyproject.toml").write_text(content)


def write_package_json(path, name, version, dependencies=None):
    path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "dependencies": dependencies or {},
            }
        )
    )


def test_detects_python_internal_dependency_version_drift(tmp_path):
    write_pyproject(tmp_path / "packages" / "core", "ao-core", "2.0.0")
    write_pyproject(
        tmp_path / "packages" / "api",
        "ao-api",
        "1.4.0",
        ["ao-core==1.9.0"],
    )

    packages = discover_packages(tmp_path)
    findings = find_version_drift(packages, ["ao-core"])

    assert len(findings) == 1
    assert findings[0].dependent == "ao-api"
    assert findings[0].dependency == "ao-core"
    assert findings[0].declared_range == "==1.9.0"
    assert findings[0].dependency_version == "2.0.0"


def test_accepts_compatible_internal_dependency_range(tmp_path):
    write_pyproject(tmp_path / "packages" / "core", "ao-core", "2.1.0")
    write_pyproject(
        tmp_path / "packages" / "api",
        "ao-api",
        "1.4.0",
        ["ao-core>=2.0.0,<3.0.0"],
    )

    packages = discover_packages(tmp_path)

    assert find_version_drift(packages, ["ao-core"]) == []


def test_reports_affected_package_pairs_in_cli_output(tmp_path, capsys):
    write_package_json(tmp_path / "packages" / "core", "@ao/core", "2.0.0")
    write_package_json(
        tmp_path / "packages" / "sdk",
        "@ao/sdk",
        "1.0.0",
        {"@ao/core": "^1.5.0"},
    )

    result = main(
        [
            "--workspace-root",
            str(tmp_path),
            "--changed-package",
            "@ao/core",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "@ao/sdk depends on @ao/core" in captured.err
    assert "^1.5.0" in captured.err
    assert "@ao/core is now 2.0.0" in captured.err


def test_version_range_supports_common_python_and_node_specifiers():
    assert version_satisfies("2.1.0", ">=2.0.0,<3.0.0")
    assert not version_satisfies("3.0.0", ">=2.0.0,<3.0.0")
    assert version_satisfies("1.4.5", "~=1.4")
    assert not version_satisfies("2.0.0", "~=1.4")
    assert version_satisfies("1.8.0", "^1.5.0")
    assert not version_satisfies("2.0.0", "^1.5.0")
    assert version_satisfies("0.2.5", "~0.2.0")
    assert not version_satisfies("0.3.0", "~0.2.0")
