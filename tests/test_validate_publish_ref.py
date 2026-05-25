from scripts.validate_publish_ref import is_protected_publish_ref


def test_accepts_protected_main_branch_for_manual_publish():
    assert is_protected_publish_ref(
        "refs/heads/main",
        "true",
        "workflow_dispatch",
    )


def test_rejects_unprotected_manual_branch_before_auth():
    assert not is_protected_publish_ref(
        "refs/heads/feature/package-test",
        "false",
        "workflow_dispatch",
    )


def test_manual_inputs_cannot_override_ref_protection():
    assert not is_protected_publish_ref(
        "refs/heads/main",
        "false",
        "workflow_dispatch",
    )


def test_accepts_signed_release_tag_shape():
    assert is_protected_publish_ref(
        "refs/tags/v2.4.1",
        "false",
        "push",
        tag_signed=True,
    )


def test_rejects_unsigned_release_tag_shape():
    assert not is_protected_publish_ref(
        "refs/tags/v2.4.1",
        "false",
        "push",
        tag_signed=False,
    )


def test_rejects_non_release_tag_shape():
    assert not is_protected_publish_ref(
        "refs/tags/latest",
        "false",
        "push",
        tag_signed=True,
    )
