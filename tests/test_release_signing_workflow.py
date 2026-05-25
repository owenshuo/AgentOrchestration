from pathlib import Path

import pytest
import yaml

from scripts.check_release_signing_summary import validate_signing_summary


WORKFLOW = Path(".github/workflows/release-signing.yml")


def load_workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def test_release_signing_uses_tag_specific_concurrency_without_cancellation():
    workflow = load_workflow()

    assert workflow["concurrency"]["group"] == (
        "release-signing-${{ github.ref_name }}"
    )
    assert workflow["concurrency"]["cancel-in-progress"] is False

    sign_job = workflow["jobs"]["sign-artifacts"]
    assert sign_job["concurrency"]["group"] == (
        "release-signing-${{ github.ref_name }}-sign-artifacts"
    )
    assert sign_job["concurrency"]["cancel-in-progress"] is False

    summary_job = workflow["jobs"]["release-summary"]
    assert summary_job["concurrency"]["group"] == (
        "release-signing-${{ github.ref_name }}-summary"
    )
    assert summary_job["concurrency"]["cancel-in-progress"] is False


def test_release_signing_runs_for_immutable_tags_only():
    workflow = load_workflow()

    assert workflow[True]["push"]["tags"] == ["v*"]
    assert "branches" not in workflow[True]["push"]


def test_release_summary_fails_when_signing_job_did_not_succeed():
    workflow = load_workflow()
    summary_steps = workflow["jobs"]["release-summary"]["steps"]

    failure_step = next(
        step
        for step in summary_steps
        if step.get("name") == "Fail partial signing states"
    )
    assert failure_step["if"] == "needs.sign-artifacts.result != 'success'"
    assert "exit 1" in failure_step["run"]


def test_signing_summary_rejects_missing_or_partial_signatures(tmp_path):
    summary = tmp_path / "summary"
    summary.mkdir()
    artifact = tmp_path / "agent.tar.gz"
    artifact.write_text("payload")
    (summary / "artifacts.txt").write_text(str(artifact))
    (summary / "signatures.txt").write_text("")

    with pytest.raises(ValueError, match="partial signing state"):
        validate_signing_summary(summary)


def test_signing_summary_accepts_complete_artifact_signatures(tmp_path):
    summary = tmp_path / "summary"
    summary.mkdir()
    artifact = tmp_path / "agent.tar.gz"
    signature = tmp_path / "agent.tar.gz.sig"
    artifact.write_text("payload")
    signature.write_text("signature")
    (summary / "artifacts.txt").write_text(str(artifact))
    (summary / "signatures.txt").write_text(str(signature))

    validate_signing_summary(summary)
