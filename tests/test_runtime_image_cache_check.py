import os
import stat
import subprocess
from pathlib import Path


def _write_fake_docker(bin_dir: Path, cache_root: Path) -> None:
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"$1\" != \"run\" ]; then exit 2; fi\n"
        "script=\"${@: -1}\"\n"
        f"CACHE_CHECK_ROOT={cache_root} sh -c \"$script\"\n"
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)


def _run_cache_check(tmp_path: Path, cache_root: Path) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_docker(bin_dir, cache_root)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", "scripts/check_runtime_image_caches.sh", "runtime:test"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_runtime_cache_check_passes_when_cache_paths_are_empty(tmp_path: Path) -> None:
    cache_root = tmp_path / "rootfs"
    for path in (
        "var/cache/apt",
        "var/lib/apt/lists",
        "root/.cache",
        "home/ao/.cache",
        "tmp",
        "var/tmp",
    ):
        (cache_root / path).mkdir(parents=True)

    result = _run_cache_check(tmp_path, cache_root)

    assert result.returncode == 0, result.stderr


def test_runtime_cache_check_fails_when_cache_files_remain(tmp_path: Path) -> None:
    cache_root = tmp_path / "rootfs"
    cache_dir = cache_root / "var/cache/apt"
    cache_dir.mkdir(parents=True)
    (cache_dir / "pkg.bin").write_text("cached")

    result = _run_cache_check(tmp_path, cache_root)

    assert result.returncode == 1
    assert "Runtime image contains cache files in" in result.stderr
    assert "var/cache/apt" in result.stderr
