"""Service account provisioning and external ID uniqueness checks."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class ServiceAccountStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ServiceAccountProvisioner:
    def __init__(self):
        self._accounts: Dict[str, Dict[str, Any]] = {}

    def create(
        self,
        organization_id: str,
        name: str,
        external_id: Optional[str] = None,
        disabled: bool = False,
    ) -> str:
        status = (
            ServiceAccountStatus.DISABLED
            if disabled
            else ServiceAccountStatus.ACTIVE
        )
        if status is ServiceAccountStatus.ACTIVE:
            self._ensure_external_id_available(organization_id, external_id)

        account_id = str(uuid.uuid4())
        timestamp = time.time()
        self._accounts[account_id] = {
            "id": account_id,
            "organization_id": organization_id,
            "name": name,
            "external_id": self._normalize_external_id(external_id),
            "status": status.value,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        return account_id

    def get(self, account_id: str) -> Optional[Dict[str, Any]]:
        account = self._accounts.get(account_id)
        return dict(account) if account else None

    def update(
        self,
        account_id: str,
        name: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> bool:
        account = self._accounts.get(account_id)
        if not account:
            return False

        next_external_id = (
            account["external_id"]
            if external_id is None
            else self._normalize_external_id(external_id)
        )
        if account["status"] == ServiceAccountStatus.ACTIVE.value:
            self._ensure_external_id_available(
                account["organization_id"],
                next_external_id,
                exclude_account_id=account_id,
            )

        if name is not None:
            account["name"] = name
        account["external_id"] = next_external_id
        account["updated_at"] = time.time()
        return True

    def disable(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if not account:
            return False
        account["status"] = ServiceAccountStatus.DISABLED.value
        account["updated_at"] = time.time()
        return True

    def restore(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if not account:
            return False
        self._ensure_external_id_available(
            account["organization_id"],
            account["external_id"],
            exclude_account_id=account_id,
        )
        account["status"] = ServiceAccountStatus.ACTIVE.value
        account["updated_at"] = time.time()
        return True

    def find_duplicate_active_external_ids(self) -> Dict[str, List[str]]:
        duplicates: Dict[str, List[str]] = {}
        seen: Dict[str, str] = {}

        for account in self._accounts.values():
            if account["status"] != ServiceAccountStatus.ACTIVE.value:
                continue
            external_id = account["external_id"]
            if not external_id:
                continue
            key = self._external_id_key(
                account["organization_id"],
                external_id,
            )
            if key in seen:
                duplicates.setdefault(key, [seen[key]]).append(account["id"])
            else:
                seen[key] = account["id"]

        return duplicates

    def _ensure_external_id_available(
        self,
        organization_id: str,
        external_id: Optional[str],
        exclude_account_id: Optional[str] = None,
    ) -> None:
        normalized = self._normalize_external_id(external_id)
        if not normalized:
            return

        for account_id, account in self._accounts.items():
            if account_id == exclude_account_id:
                continue
            if account["organization_id"] != organization_id:
                continue
            if account["status"] != ServiceAccountStatus.ACTIVE.value:
                continue
            if account["external_id"] == normalized:
                raise ValueError(
                    "external_id must be unique among active service "
                    "accounts in an organization"
                )

    @staticmethod
    def _normalize_external_id(external_id: Optional[str]) -> Optional[str]:
        if external_id is None:
            return None
        normalized = external_id.strip()
        return normalized or None

    @staticmethod
    def _external_id_key(organization_id: str, external_id: str) -> str:
        return f"{organization_id}:{external_id}"
