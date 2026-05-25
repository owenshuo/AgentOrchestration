import json

import pytest

from scripts.validate_release_image_target import main
from src.release.image_targets import (
    ReleaseImageTarget,
    ReleaseTargetError,
    ReleaseTargetValidator,
)


def test_rejects_unapproved_namespace_before_push_summary():
    validator = ReleaseTargetValidator({"ghcr.io/orchestration-agent"})
    target = ReleaseImageTarget.parse("ghcr.io/other/worker:v1.2.3")

    with pytest.raises(
        ReleaseTargetError,
        match="unapproved registry namespace",
    ):
        validator.validate_before_push(target)


def test_rejects_invalid_tag_before_namespace_approval():
    validator = ReleaseTargetValidator({"ghcr.io/orchestration-agent"})
    target = ReleaseImageTarget(
        registry="ghcr.io",
        namespace="orchestration-agent",
        image="worker",
        tag="../latest",
    )

    with pytest.raises(ReleaseTargetError, match="invalid image tag"):
        validator.validate_before_push(target)


def test_approved_namespace_returns_safe_release_summary():
    validator = ReleaseTargetValidator({"ghcr.io/orchestration-agent"})
    target = ReleaseImageTarget.parse(
        "ghcr.io/orchestration-agent/worker:v1.2.3",
    )

    summary = validator.validate_before_push(target)

    assert summary == {
        "registry": "ghcr.io",
        "namespace": "orchestration-agent",
        "image": "worker",
        "tag": "v1.2.3",
        "approved_target": "ghcr.io/orchestration-agent/worker:v1.2.3",
    }
    assert "token" not in json.dumps(summary).lower()
    assert "password" not in json.dumps(summary).lower()


def test_cli_fails_unapproved_target_before_push(capsys):
    status = main([
        "ghcr.io/other/worker:v1.2.3",
        "--allow",
        "ghcr.io/orchestration-agent",
    ])

    captured = capsys.readouterr()
    assert status == 1
    assert "unapproved registry namespace" in captured.err
    assert captured.out == ""


def test_cli_prints_approved_target_summary(capsys):
    status = main([
        "ghcr.io/orchestration-agent/worker:v1.2.3",
        "--allow",
        "ghcr.io/orchestration-agent",
    ])

    captured = capsys.readouterr()
    assert status == 0
    assert json.loads(captured.out) == {
        "registry": "ghcr.io",
        "namespace": "orchestration-agent",
        "image": "worker",
        "tag": "v1.2.3",
        "approved_target": "ghcr.io/orchestration-agent/worker:v1.2.3",
    }
