from pathlib import Path

import yaml


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "release.yml"
)


def load_workflow():
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def get_action_step(workflow, action_name):
    steps = workflow["jobs"]["publish"]["steps"]
    return next(
        step for step in steps if step.get("uses", "").startswith(action_name)
    )


def test_release_workflow_runs_for_version_tags():
    workflow = load_workflow()
    event_config = workflow.get("on", workflow.get(True))

    assert event_config["push"]["tags"] == ["v*"]


def test_release_workflow_has_attestation_permissions():
    workflow = load_workflow()

    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
    assert workflow["permissions"]["attestations"] == "write"


def test_release_artifacts_are_attested_before_upload():
    workflow = load_workflow()
    steps = workflow["jobs"]["publish"]["steps"]
    names = [step["name"] for step in steps]

    build_index = names.index("Build release archives")
    attest_index = names.index("Generate build provenance attestations")
    artifact_index = names.index("Upload workflow artifacts")
    release_index = names.index("Publish GitHub release assets")

    assert build_index < attest_index < artifact_index < release_index

    attestation_step = get_action_step(
        workflow, "actions/attest-build-provenance"
    )
    assert attestation_step["with"]["subject-path"] == "dist/*"


def test_release_uploads_match_attested_artifacts():
    workflow = load_workflow()
    attestation_step = get_action_step(
        workflow, "actions/attest-build-provenance"
    )
    artifact_step = get_action_step(workflow, "actions/upload-artifact")
    release_step = get_action_step(workflow, "softprops/action-gh-release")

    attested_path = attestation_step["with"]["subject-path"]
    assert artifact_step["with"]["if-no-files-found"] == "error"
    assert artifact_step["with"]["path"] == attested_path
    assert release_step["with"]["files"] == attested_path


def test_release_documentation_includes_attestation_verification():
    readme = WORKFLOW_PATH.parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "gh attestation verify" in text
    assert "--repo orchestration-agent/AgentOrchestration" in text
    assert "Release" in text
