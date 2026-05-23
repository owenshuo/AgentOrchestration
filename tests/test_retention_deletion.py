from src.data.retention_deletion import (
    InMemoryRetentionStore,
    RetentionDeletionWorkflow,
)


def build_workflow():
    stores = {
        "artifacts": InMemoryRetentionStore("artifacts"),
        "embeddings": InMemoryRetentionStore("embeddings"),
        "indexes": InMemoryRetentionStore("indexes"),
    }
    return RetentionDeletionWorkflow(stores), stores


class TestRetentionDeletionWorkflow:
    def test_delete_manifest_cascades_to_primary_and_derived_stores(self):
        workflow, stores = build_workflow()
        for store in stores.values():
            store.put(
                f"{store.name}-1",
                artifact_id="task-1",
                workspace_id="ws-1",
            )
            store.put(
                f"{store.name}-2",
                artifact_id="task-2",
                workspace_id="ws-1",
            )
            store.put(
                f"{store.name}-other",
                artifact_id="task-1",
                workspace_id="ws-2",
            )

        manifest = workflow.build_manifest("ws-1", ["task-1"])
        result = workflow.execute(manifest)

        assert [record["store"] for record in result["stores"]] == [
            "artifacts",
            "embeddings",
            "indexes",
        ]
        assert all(record["deleted"] == 1 for record in result["stores"])
        assert not stores["artifacts"].has_artifact("ws-1", "task-1")
        assert not stores["embeddings"].has_artifact("ws-1", "task-1")
        assert not stores["indexes"].has_artifact("ws-1", "task-1")
        assert stores["embeddings"].has_artifact("ws-2", "task-1")
        assert stores["artifacts"].has_artifact("ws-1", "task-2")

    def test_completion_records_list_every_affected_store(self):
        workflow, stores = build_workflow()
        stores["artifacts"].put(
            "artifact",
            artifact_id="task-1",
            workspace_id="ws-1",
        )
        stores["embeddings"].put(
            "embedding",
            artifact_id="task-1",
            workspace_id="ws-1",
        )
        stores["indexes"].put(
            "index",
            artifact_id="task-1",
            workspace_id="ws-1",
        )

        workflow.execute(workflow.build_manifest("ws-1", ["task-1"]))

        records = workflow.completion_records()
        assert {record["store"] for record in records} == {
            "artifacts",
            "embeddings",
            "indexes",
        }
        assert all(record["workspace_id"] == "ws-1" for record in records)
        assert all("completed_at" in record for record in records)

    def test_reconcile_removes_stale_derived_records(self):
        workflow, stores = build_workflow()
        stores["artifacts"].put(
            "artifact",
            artifact_id="live",
            workspace_id="ws-1",
        )
        stores["embeddings"].put(
            "live-embedding",
            artifact_id="live",
            workspace_id="ws-1",
        )
        stores["embeddings"].put(
            "stale-embedding",
            artifact_id="stale",
            workspace_id="ws-1",
        )
        stores["indexes"].put(
            "stale-index",
            artifact_id="stale",
            workspace_id="ws-1",
        )

        result = workflow.reconcile("ws-1")

        assert {record["store"] for record in result["removed"]} == {
            "embeddings",
            "indexes",
        }
        assert not stores["embeddings"].has_artifact("ws-1", "stale")
        assert not stores["indexes"].has_artifact("ws-1", "stale")
        assert stores["embeddings"].has_artifact("ws-1", "live")
        assert all(record["reconciled"] for record in result["removed"])
