"""Purpose-limited data lake ingestion validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Set


class PurposePolicyError(ValueError):
    """Raised when a data lake write violates purpose policy."""


@dataclass(frozen=True)
class IngestionManifest:
    purpose: str
    data_class: str
    owner: str
    destination: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "IngestionManifest":
        missing = [
            key
            for key in ("purpose", "data_class", "owner", "destination")
            if not str(payload.get(key, "")).strip()
        ]
        if missing:
            raise PurposePolicyError(
                "data lake manifest missing required fields: "
                f"{', '.join(sorted(missing))}"
            )

        return cls(
            purpose=str(payload["purpose"]).strip(),
            data_class=str(payload["data_class"]).strip(),
            owner=str(payload["owner"]).strip(),
            destination=str(payload["destination"]).strip(),
        )


@dataclass(frozen=True)
class DestinationPolicy:
    destination: str
    allowed_data_classes: Set[str]
    approved_purposes: Set[str] = field(default_factory=set)

    @classmethod
    def build(
        cls,
        destination: str,
        allowed_data_classes: Iterable[str],
        approved_purposes: Iterable[str] | None = None,
    ) -> "DestinationPolicy":
        return cls(
            destination=destination,
            allowed_data_classes={
                item for item in allowed_data_classes if item
            },
            approved_purposes={
                item for item in (approved_purposes or []) if item
            },
        )

    def allows(self, manifest: IngestionManifest) -> bool:
        if manifest.data_class not in self.allowed_data_classes:
            return False
        if (
            self.approved_purposes
            and manifest.purpose not in self.approved_purposes
        ):
            return False
        return True


@dataclass(frozen=True)
class DataLakeWrite:
    manifest: IngestionManifest
    record_count: int


@dataclass(frozen=True)
class DataLakeAuditReport:
    by_purpose: Dict[str, int]
    by_owner: Dict[str, int]
    writes: List[Dict[str, Any]]


class DataLakeGovernance:
    def __init__(self):
        self._destination_policies: Dict[str, DestinationPolicy] = {}
        self._writes: List[DataLakeWrite] = []

    def register_destination(
        self,
        destination: str,
        allowed_data_classes: Iterable[str],
        approved_purposes: Iterable[str] | None = None,
    ) -> None:
        policy = DestinationPolicy.build(
            destination,
            allowed_data_classes,
            approved_purposes,
        )
        if not policy.allowed_data_classes:
            raise PurposePolicyError(
                f"destination {destination} must allow at least one data class"
            )
        self._destination_policies[destination] = policy

    def validate_manifest(
        self,
        manifest_payload: Mapping[str, Any],
    ) -> IngestionManifest:
        manifest = IngestionManifest.from_mapping(manifest_payload)
        policy = self._destination_policies.get(manifest.destination)
        if policy is None:
            raise PurposePolicyError(
                f"destination {manifest.destination} is not approved"
            )
        if not policy.allows(manifest):
            raise PurposePolicyError(
                f"destination {manifest.destination} does not allow "
                f"{manifest.data_class} for purpose {manifest.purpose}"
            )
        return manifest

    def write(
        self,
        records: Iterable[Mapping[str, Any]],
        manifest_payload: Mapping[str, Any],
    ) -> DataLakeWrite:
        manifest = self.validate_manifest(manifest_payload)
        record_count = sum(1 for _ in records)
        write = DataLakeWrite(manifest=manifest, record_count=record_count)
        self._writes.append(write)
        return write

    def audit_report(self) -> DataLakeAuditReport:
        by_purpose: Dict[str, int] = {}
        by_owner: Dict[str, int] = {}
        writes: List[Dict[str, Any]] = []

        for write in self._writes:
            manifest = write.manifest
            by_purpose[manifest.purpose] = (
                by_purpose.get(manifest.purpose, 0) + write.record_count
            )
            by_owner[manifest.owner] = (
                by_owner.get(manifest.owner, 0) + write.record_count
            )
            writes.append(
                {
                    "purpose": manifest.purpose,
                    "data_class": manifest.data_class,
                    "owner": manifest.owner,
                    "destination": manifest.destination,
                    "record_count": write.record_count,
                }
            )

        return DataLakeAuditReport(
            by_purpose=by_purpose,
            by_owner=by_owner,
            writes=writes,
        )
