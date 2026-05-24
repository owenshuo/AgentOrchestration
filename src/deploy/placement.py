"""Validate worker placement against documented workload policies."""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


class PlacementValidationError(ValueError):
    """Raised when a worker manifest violates placement policy."""


@dataclass(frozen=True)
class PlacementPolicy:
    workload_class: str
    node_selector: Mapping[str, str]
    tolerations: Tuple[Mapping[str, str], ...] = field(default_factory=tuple)
    affinity_required: bool = False


DEFAULT_POLICIES: Dict[str, PlacementPolicy] = {
    "cpu": PlacementPolicy(
        workload_class="cpu",
        node_selector={"workload.agent/orchestration": "cpu"},
    ),
    "gpu": PlacementPolicy(
        workload_class="gpu",
        node_selector={
            "workload.agent/orchestration": "gpu",
            "accelerator.agent/type": "nvidia",
        },
        tolerations=(
            {
                "key": "nvidia.com/gpu",
                "operator": "Exists",
                "effect": "NoSchedule",
            },
        ),
    ),
    "isolated": PlacementPolicy(
        workload_class="isolated",
        node_selector={"workload.agent/isolation": "dedicated"},
        tolerations=(
            {
                "key": "agent/dedicated",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            },
        ),
        affinity_required=True,
    ),
}


class WorkerPlacementValidator:
    def __init__(
        self, policies: Optional[Mapping[str, PlacementPolicy]] = None
    ):
        self._policies = dict(policies or DEFAULT_POLICIES)

    def validate(self, manifest: Mapping[str, Any]) -> Dict[str, Any]:
        workload_class = self._workload_class(manifest)
        policy = self._policies.get(workload_class)
        if policy is None:
            raise PlacementValidationError(
                f"Unsupported workload class: {workload_class}"
            )

        pod_spec = self._pod_spec(manifest)
        node_selector = pod_spec.get("nodeSelector") or {}
        tolerations = pod_spec.get("tolerations") or []
        affinity = pod_spec.get("affinity") or {}

        missing = {
            key: value
            for key, value in policy.node_selector.items()
            if node_selector.get(key) != value
        }
        if missing:
            raise PlacementValidationError(
                "nodeSelector does not match placement policy for "
                f"{workload_class}: {missing}"
            )

        missing_tolerations = [
            expected
            for expected in policy.tolerations
            if not any(
                self._matches_toleration(expected, actual)
                for actual in tolerations
            )
        ]
        if missing_tolerations:
            raise PlacementValidationError(
                "tolerations do not match placement policy for "
                f"{workload_class}: {missing_tolerations}"
            )

        if policy.affinity_required and not affinity:
            raise PlacementValidationError(
                f"affinity is required for workload class {workload_class}"
            )

        return {
            "name": manifest.get("metadata", {}).get("name"),
            "workload_class": workload_class,
            "placement_policy": {
                "node_selector": dict(policy.node_selector),
                "tolerations": [dict(item) for item in policy.tolerations],
                "affinity_required": policy.affinity_required,
            },
        }

    def _workload_class(self, manifest: Mapping[str, Any]) -> str:
        labels = manifest.get("metadata", {}).get("labels", {})
        annotations = manifest.get("metadata", {}).get("annotations", {})
        workload_class = (
            labels.get("agent.openai/workload-class")
            or annotations.get("agent.openai/workload-class")
        )
        if not workload_class:
            raise PlacementValidationError("workload class is required")
        return str(workload_class)

    def _pod_spec(self, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return manifest["spec"]["template"]["spec"]
        except KeyError as exc:
            raise PlacementValidationError(
                "manifest pod spec is required"
            ) from exc

    @staticmethod
    def _matches_toleration(
        expected: Mapping[str, str], actual: Mapping[str, str]
    ) -> bool:
        return all(actual.get(key) == value for key, value in expected.items())
