"""Data lake ingestion governance controls."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


@dataclass(frozen=True)
class DestinationPolicy:
    """Allowed data classes for a data lake destination."""

    destination: str
    allowed_data_classes: Set[str]


@dataclass(frozen=True)
class IngestionManifest:
    """Manifest required before writing operational data to the lake."""

    purpose: str
    data_class: str
    owner: str
    destination: str
    source: str = "operational-events"
    metadata: Dict[str, Any] = field(default_factory=dict)


class DataLakePolicyError(ValueError):
    """Raised when a data lake write violates governance policy."""


class DataClassificationRegistry:
    def __init__(self):
        self._policies: Dict[str, DestinationPolicy] = {}

    def register_destination(
        self,
        destination: str,
        allowed_data_classes: Set[str],
    ) -> None:
        destination = self._require_text("destination", destination)
        if not allowed_data_classes:
            raise DataLakePolicyError("allowed data classes are required")
        normalized_classes = {
            self._require_text("data_class", data_class)
            for data_class in allowed_data_classes
        }
        self._policies[destination] = DestinationPolicy(
            destination=destination,
            allowed_data_classes=normalized_classes,
        )

    def allows(self, destination: str, data_class: str) -> bool:
        policy = self._policies.get(destination)
        return bool(policy and data_class in policy.allowed_data_classes)

    def _require_text(self, field_name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DataLakePolicyError(f"{field_name} is required")
        return value.strip()


class DataLakeIngestionPipeline:
    def __init__(self, registry: Optional[DataClassificationRegistry] = None):
        self.registry = registry or DataClassificationRegistry()
        self._writes: List[Dict[str, Any]] = []
        self.audit_records: List[Dict[str, Any]] = []

    def ingest(
        self,
        payload: Dict[str, Any],
        manifest: IngestionManifest,
    ) -> Dict[str, Any]:
        self._validate_manifest(manifest)
        if not self.registry.allows(manifest.destination, manifest.data_class):
            self._record_audit(
                manifest,
                "rejected",
                reason="destination_policy_denied",
            )
            raise DataLakePolicyError(
                "destination policy does not allow data class"
            )

        write = {
            "write_id": str(uuid4()),
            "destination": manifest.destination,
            "purpose": manifest.purpose,
            "data_class": manifest.data_class,
            "owner": manifest.owner,
            "source": manifest.source,
            "metadata": dict(manifest.metadata),
            "payload": dict(payload),
            "created_at": time.time(),
        }
        self._writes.append(write)
        self._record_audit(manifest, "accepted", write_id=write["write_id"])
        return dict(write)

    def audit_report(self) -> List[Dict[str, Any]]:
        report: Dict[tuple, Dict[str, Any]] = {}
        for record in self.audit_records:
            if record["decision"] != "accepted":
                continue
            key = (record["purpose"], record["owner"])
            summary = report.setdefault(
                key,
                {
                    "purpose": record["purpose"],
                    "owner": record["owner"],
                    "write_count": 0,
                    "destinations": set(),
                    "data_classes": set(),
                },
            )
            summary["write_count"] += 1
            summary["destinations"].add(record["destination"])
            summary["data_classes"].add(record["data_class"])

        return [
            {
                **summary,
                "destinations": sorted(summary["destinations"]),
                "data_classes": sorted(summary["data_classes"]),
            }
            for summary in report.values()
        ]

    def _validate_manifest(self, manifest: IngestionManifest) -> None:
        for field_name in ("purpose", "data_class", "owner", "destination"):
            value = getattr(manifest, field_name)
            if not isinstance(value, str) or not value.strip():
                self._record_audit(
                    manifest,
                    "rejected",
                    reason=f"missing_{field_name}",
                )
                raise DataLakePolicyError(f"{field_name} is required")

    def _record_audit(
        self,
        manifest: IngestionManifest,
        decision: str,
        **fields: Any,
    ) -> None:
        self.audit_records.append(
            {
                "decision": decision,
                "purpose": manifest.purpose,
                "data_class": manifest.data_class,
                "owner": manifest.owner,
                "destination": manifest.destination,
                "source": manifest.source,
                "timestamp": time.time(),
                **fields,
            }
        )
