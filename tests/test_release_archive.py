import hashlib
import json
import tarfile
from pathlib import Path

from scripts.release_archive import build_release_archive


def test_release_archive_normalizes_text_line_endings(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_bytes(b"one\r\ntwo\r\n")
    (source / "pyproject.toml").write_bytes(b"[project]\r\nname='ao'\r\n")

    crlf_archive = tmp_path / "crlf.tar.gz"
    crlf_digest, entries = build_release_archive(
        source,
        crlf_archive,
        ["README.md", "pyproject.toml"],
    )

    (source / "README.md").write_bytes(b"one\ntwo\n")
    (source / "pyproject.toml").write_bytes(b"[project]\nname='ao'\n")
    lf_archive = tmp_path / "lf.tar.gz"
    lf_digest, _ = build_release_archive(
        source,
        lf_archive,
        ["README.md", "pyproject.toml"],
    )

    assert crlf_digest == lf_digest
    assert crlf_archive.read_bytes() == lf_archive.read_bytes()
    assert {entry.line_endings for entry in entries} == {"LF"}


def test_release_archive_manifest_declares_line_ending_policy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_bytes(b"hello\r\n")
    archive_path = tmp_path / "release.tar.gz"

    build_release_archive(source, archive_path, ["README.md"])

    with tarfile.open(archive_path, "r:gz") as archive:
        readme = archive.extractfile("README.md").read()
        manifest = json.loads(
            archive.extractfile("RELEASE-LINE-ENDINGS.json").read()
        )

    assert readme == b"hello\n"
    assert manifest["line_ending_policy"] == (
        "text files are normalized to LF before hashing"
    )
    assert manifest["entries"][0]["line_endings"] == "LF"


def test_checksum_file_uses_archive_digest_and_lf_newline(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("hello\n", encoding="utf-8")
    archive_path = tmp_path / "release.tar.gz"

    digest, _ = build_release_archive(source, archive_path, ["README.md"])

    checksum = Path(str(archive_path) + ".sha256").read_text(
        encoding="utf-8"
    )
    assert checksum == f"{digest}  release.tar.gz\n"
    assert digest == hashlib.sha256(archive_path.read_bytes()).hexdigest()
