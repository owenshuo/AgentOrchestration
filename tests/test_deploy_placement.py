import pytest

from src.deploy import PlacementValidationError, WorkerPlacementValidator


def _manifest(
    workload_class="gpu", node_selector=None, tolerations=None, affinity=None
):
    return {
        "metadata": {
            "name": "worker-gpu",
            "labels": {"agent.openai/workload-class": workload_class},
        },
        "spec": {
            "template": {
                "spec": {
                    "nodeSelector": node_selector or {
                        "workload.agent/orchestration": "gpu",
                        "accelerator.agent/type": "nvidia",
                    },
                    "tolerations": tolerations
                    if tolerations is not None
                    else [
                        {
                            "key": "nvidia.com/gpu",
                            "operator": "Exists",
                            "effect": "NoSchedule",
                        }
                    ],
                    "affinity": affinity or {},
                }
            }
        },
    }


def test_valid_worker_manifest_returns_deployment_summary():
    summary = WorkerPlacementValidator().validate(_manifest())

    assert summary["name"] == "worker-gpu"
    assert summary["workload_class"] == "gpu"
    assert summary["placement_policy"]["node_selector"] == {
        "workload.agent/orchestration": "gpu",
        "accelerator.agent/type": "nvidia",
    }


def test_missing_workload_class_is_rejected():
    manifest = _manifest()
    manifest["metadata"]["labels"] = {}

    with pytest.raises(PlacementValidationError, match="workload class"):
        WorkerPlacementValidator().validate(manifest)


def test_node_selector_drift_is_rejected():
    manifest = _manifest(
        node_selector={
            "workload.agent/orchestration": "cpu",
            "accelerator.agent/type": "nvidia",
        }
    )

    with pytest.raises(PlacementValidationError, match="nodeSelector"):
        WorkerPlacementValidator().validate(manifest)


def test_toleration_drift_is_rejected():
    manifest = _manifest(tolerations=[])

    with pytest.raises(PlacementValidationError, match="tolerations"):
        WorkerPlacementValidator().validate(manifest)


def test_affinity_required_for_isolated_workers():
    manifest = _manifest(
        workload_class="isolated",
        node_selector={"workload.agent/isolation": "dedicated"},
        tolerations=[
            {
                "key": "agent/dedicated",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            }
        ],
        affinity={},
    )

    with pytest.raises(PlacementValidationError, match="affinity"):
        WorkerPlacementValidator().validate(manifest)


def test_isolated_worker_with_affinity_passes():
    manifest = _manifest(
        workload_class="isolated",
        node_selector={"workload.agent/isolation": "dedicated"},
        tolerations=[
            {
                "key": "agent/dedicated",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            }
        ],
        affinity={
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {}
            }
        },
    )

    summary = WorkerPlacementValidator().validate(manifest)

    assert summary["workload_class"] == "isolated"
    assert summary["placement_policy"]["affinity_required"] is True
