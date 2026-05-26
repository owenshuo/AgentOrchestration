import pytest

from src.identity.service_accounts import ServiceAccountProvisioner


def test_create_rejects_duplicate_active_external_id_in_organization():
    provisioner = ServiceAccountProvisioner()
    provisioner.create("org-a", "deploy", external_id="idp-123")

    with pytest.raises(ValueError, match="external_id must be unique"):
        provisioner.create("org-a", "rotate", external_id="idp-123")


def test_create_allows_same_external_id_in_different_organizations():
    provisioner = ServiceAccountProvisioner()
    first = provisioner.create("org-a", "deploy", external_id="idp-123")
    second = provisioner.create("org-b", "deploy", external_id="idp-123")

    assert first != second


def test_update_rejects_duplicate_active_external_id():
    provisioner = ServiceAccountProvisioner()
    first = provisioner.create("org-a", "deploy", external_id="idp-123")
    second = provisioner.create("org-a", "rotate", external_id="idp-456")

    assert provisioner.update(first, external_id=" idp-123 ")
    with pytest.raises(ValueError, match="external_id must be unique"):
        provisioner.update(second, external_id="idp-123")


def test_disabled_accounts_do_not_block_external_id_reuse():
    provisioner = ServiceAccountProvisioner()
    disabled = provisioner.create(
        "org-a",
        "old-deploy",
        external_id="idp-123",
        disabled=True,
    )
    active = provisioner.create("org-a", "new-deploy", external_id="idp-123")

    assert provisioner.get(disabled)["status"] == "disabled"
    assert provisioner.get(active)["status"] == "active"


def test_restore_rechecks_external_id_uniqueness():
    provisioner = ServiceAccountProvisioner()
    disabled = provisioner.create(
        "org-a",
        "old-deploy",
        external_id="idp-123",
        disabled=True,
    )
    provisioner.create("org-a", "new-deploy", external_id="idp-123")

    with pytest.raises(ValueError, match="external_id must be unique"):
        provisioner.restore(disabled)


def test_disabled_account_reuse_is_rechecked_on_restore():
    provisioner = ServiceAccountProvisioner()
    old_account = provisioner.create("org-a", "old", external_id="idp-123")

    assert provisioner.disable(old_account)
    provisioner.create("org-a", "new", external_id="idp-123")

    with pytest.raises(ValueError, match="external_id must be unique"):
        provisioner.restore(old_account)


def test_migration_check_reports_existing_active_duplicates():
    provisioner = ServiceAccountProvisioner()
    first = provisioner.create("org-a", "deploy", external_id="idp-123")
    second = provisioner.create(
        "org-a",
        "legacy-duplicate",
        external_id="idp-123",
        disabled=True,
    )
    provisioner._accounts[second]["status"] = "active"

    assert provisioner.find_duplicate_active_external_ids() == {
        "org-a:idp-123": [first, second],
    }
