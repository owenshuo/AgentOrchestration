"""Validate release signing summary files."""

from pathlib import Path
import sys


def read_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def validate_signing_summary(summary_dir: Path) -> None:
    artifacts = read_entries(summary_dir / "artifacts.txt")
    signatures = read_entries(summary_dir / "signatures.txt")

    if not artifacts:
        raise ValueError("release summary contains no artifacts")
    if len(artifacts) != len(signatures):
        raise ValueError(
            "partial signing state: artifact/signature count mismatch"
        )

    missing = [
        signature for signature in signatures if not Path(signature).exists()
    ]
    if missing:
        raise ValueError(
            "partial signing state: missing signatures "
            + ", ".join(sorted(missing))
        )

    unsigned = []
    signature_names = {Path(signature).name for signature in signatures}
    for artifact in artifacts:
        expected = Path(f"{artifact}.sig").name
        if expected not in signature_names:
            unsigned.append(artifact)

    if unsigned:
        raise ValueError(
            "partial signing state: unsigned artifacts "
            + ", ".join(sorted(unsigned))
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: check_release_signing_summary.py <summary-dir>",
            file=sys.stderr,
        )
        return 2
    try:
        validate_signing_summary(Path(argv[1]))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
