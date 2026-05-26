import pytest

from src.api.auth import (
    AuthDecision,
    CollaborationAuthService,
    Principal,
    SavedViewShareRequest,
    WorkspaceRole,
)


@pytest.fixture
def share_request():
    return SavedViewShareRequest(
        workspace_id="workspace-1",
        view_id="view-1",
        target_principal_id="user-2",
    )


def principal(**overrides):
    values = {
        "id": "user-1",
        "workspace_id": "workspace-1",
        "roles": {WorkspaceRole.MEMBER},
        "authenticated": True,
        "revoked": False,
        "stale": False,
    }
    values.update(overrides)
    return Principal(**values)


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (None, "anonymous_principal"),
        (principal(authenticated=False), "anonymous_principal"),
        (principal(stale=True), "stale_principal"),
        (principal(revoked=True), "revoked_principal"),
        (
            principal(workspace_id="workspace-2"),
            "workspace_membership_required",
        ),
        (
            principal(roles={WorkspaceRole.VIEWER}),
            "insufficient_workspace_role",
        ),
    ],
)
def test_saved_view_share_denies_invalid_or_insufficient_principals(
    share_request,
    candidate,
    reason,
):
    result = CollaborationAuthService().authorize_saved_view_share(
        candidate,
        share_request,
    )

    assert result.allowed is False
    assert result.decision == AuthDecision.DENY
    assert result.reason == reason
    assert result.audit["decision"] == "deny"
    assert result.audit["reason"] == reason


@pytest.mark.parametrize(
    "role",
    [WorkspaceRole.MEMBER, WorkspaceRole.ADMIN],
)
def test_saved_view_share_allows_workspace_members_with_share_role(
    share_request,
    role,
):
    result = CollaborationAuthService().authorize_saved_view_share(
        principal(roles={role}),
        share_request,
    )

    assert result.allowed is True
    assert result.decision == AuthDecision.ALLOW
    assert result.reason == "authorized"
    assert result.audit == {
        "decision": "allow",
        "reason": "authorized",
        "workspace_id": "workspace-1",
        "view_id": "view-1",
        "principal_id": "user-1",
    }


def test_saved_view_share_audit_does_not_expose_target_or_roles(
    share_request,
):
    result = CollaborationAuthService().authorize_saved_view_share(
        principal(roles={WorkspaceRole.ADMIN}),
        share_request,
    )

    assert "target_principal_id" not in result.audit
    assert "roles" not in result.audit


def test_saved_view_share_audit_report_summarizes_without_private_data(
    share_request,
):
    service = CollaborationAuthService()

    service.authorize_saved_view_share(
        principal(id="user-owner", roles={WorkspaceRole.ADMIN}),
        share_request,
    )
    service.authorize_saved_view_share(
        principal(id="user-limited", roles={WorkspaceRole.VIEWER}),
        share_request,
    )
    service.authorize_saved_view_share(
        principal(id="user-other", workspace_id="workspace-2"),
        share_request,
    )

    report = service.audit_report()

    assert report["total"] == 3
    assert report["allowed"] == 1
    assert report["denied"] == 2
    assert report["by_reason"] == {
        "authorized": 1,
        "insufficient_workspace_role": 1,
        "workspace_membership_required": 1,
    }
    assert len(report["recent"]) == 3
    assert "target_principal_id" not in str(report)
    assert "user-2" not in str(report)
    assert "roles" not in str(report)
    assert "viewer" not in str(report)
    assert "admin" not in str(report).lower()

    report["recent"][0]["reason"] = "changed"
    assert service.audit_events[0]["reason"] == "authorized"
