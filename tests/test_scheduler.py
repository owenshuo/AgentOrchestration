from src.orchestrator.scheduler import TaskScheduler


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestTaskScheduler:
    def setup_method(self):
        self.clock = FakeClock()
        self.scheduler = TaskScheduler(clock=self.clock)

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_deleted_workflow_prunes_queued_poll_without_payload_audit(self):
        self.scheduler.enqueue(
            {
                "type": "poll",
                "workflow_id": "workflow-1",
                "workflow_revision": 3,
                "workflow_attempt": 1,
                "lifecycle_state": "running",
                "payload": {"private": "do not audit"},
            }
        )

        removed = self.scheduler.mark_workflow_deleted(
            "workflow-1",
            revision=3,
            attempt=1,
        )

        import asyncio
        assert removed == 1
        assert asyncio.run(self.scheduler.dequeue()) is None
        audit = self.scheduler.audit_events[-1]
        assert audit["decision"] == "workflow_deleted"
        assert audit["removed_poll_tasks"] == 1
        assert "payload" not in audit

    def test_deleted_workflow_rejects_late_poll_transition(self):
        self.scheduler.mark_workflow_deleted(
            "workflow-2",
            revision=2,
            attempt=4,
        )
        poll_task = {
            "type": "poll",
            "workflow_id": "workflow-2",
            "workflow_revision": 2,
            "workflow_attempt": 4,
            "lifecycle_state": "running",
            "payload": {"private": "do not audit"},
        }

        task_id = self.scheduler.enqueue(poll_task)

        assert task_id is None
        assert poll_task["lifecycle_state"] == "running"
        audit = self.scheduler.audit_events[-1]
        assert audit["decision"] == "rejected"
        assert audit["reason"] == "workflow_deleted"
        assert audit["action"] == "enqueue"
        assert audit["workflow_id"] == "workflow-2"
        assert audit["workflow_revision"] == 2
        assert audit["workflow_attempt"] == 4
        assert "payload" not in audit

    def test_deleted_workflow_rejects_due_scheduled_poll(self):
        self.scheduler.schedule(
            {
                "type": "poll",
                "workflow_id": "workflow-3",
                "workflow_revision": 5,
                "workflow_attempt": 1,
                "lifecycle_state": "running",
            },
            delay=10,
        )
        self.scheduler.mark_workflow_deleted(
            "workflow-3",
            revision=5,
            attempt=1,
        )
        self.clock.advance(10)

        import asyncio
        assert asyncio.run(self.scheduler.dequeue()) is None

    def test_deleted_workflow_rejects_in_flight_completion(self):
        self.scheduler.enqueue(
            {
                "type": "poll",
                "workflow_id": "workflow-4",
                "workflow_revision": 1,
                "workflow_attempt": 1,
                "lifecycle_state": "running",
            }
        )
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())

        removed = self.scheduler.mark_workflow_deleted(
            "workflow-4",
            revision=1,
            attempt=1,
        )

        assert removed == 1
        assert self.scheduler.complete(task["id"]) is False

    def test_deleted_workflow_rejects_retry_and_does_not_requeue(self):
        self.scheduler.enqueue(
            {
                "type": "poll",
                "workflow_id": "workflow-5",
                "workflow_revision": 9,
                "workflow_attempt": 2,
                "lifecycle_state": "running",
            }
        )
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.mark_workflow_deleted(
            "workflow-5",
            revision=9,
            attempt=2,
        )

        assert self.scheduler.fail(task["id"]) is False
        assert asyncio.run(self.scheduler.dequeue()) is None

    def test_deleted_workflow_allows_newer_revision_poll(self):
        self.scheduler.mark_workflow_deleted(
            "workflow-6",
            revision=3,
            attempt=1,
        )
        task_id = self.scheduler.enqueue(
            {
                "type": "poll",
                "workflow_id": "workflow-6",
                "workflow_revision": 4,
                "workflow_attempt": 1,
                "lifecycle_state": "running",
            }
        )

        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task_id is not None
        assert task["workflow_revision"] == 4

    def test_late_older_cleanup_cannot_downgrade_tombstone(self):
        self.scheduler.mark_workflow_deleted(
            "workflow-8",
            revision=5,
            attempt=3,
        )
        self.scheduler.mark_workflow_deleted(
            "workflow-8",
            revision=4,
            attempt=9,
        )

        task_id = self.scheduler.enqueue(
            {
                "type": "poll",
                "workflow_id": "workflow-8",
                "workflow_revision": 5,
                "workflow_attempt": 3,
                "lifecycle_state": "running",
            }
        )

        assert task_id is None
        assert self.scheduler.audit_events[-1]["deleted_revision"] == 5
        assert self.scheduler.audit_events[-1]["deleted_attempt"] == 3

    def test_deleted_workflow_does_not_drop_non_poll_task(self):
        task_id = self.scheduler.enqueue(
            {
                "type": "execute",
                "workflow_id": "workflow-7",
                "workflow_revision": 1,
                "workflow_attempt": 1,
                "lifecycle_state": "running",
            }
        )
        self.scheduler.mark_workflow_deleted(
            "workflow-7",
            revision=1,
            attempt=1,
        )

        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task_id is not None
        assert task["type"] == "execute"

# 2019-01-09T19:07:03 update

# 2019-02-18T12:30:02 update

# 2019-04-11T16:04:51 update

# 2019-04-17T16:25:46 update

# 2019-05-24T19:32:13 update

# 2019-07-02T12:54:25 update

# 2019-07-03T20:37:00 update

# 2019-08-21T19:37:17 update

# 2019-10-18T10:30:31 update

# 2019-10-25T09:01:38 update

# 2019-10-29T12:59:34 update

# 2019-11-05T10:07:06 update

# 2019-11-11T10:43:52 update

# 2020-01-17T13:40:02 update

# 2020-02-07T14:06:34 update

# 2020-04-03T08:53:40 update

# 2020-04-06T19:36:29 update

# 2020-05-12T11:51:05 update

# 2020-08-17T08:37:15 update

# 2020-09-15T10:39:38 update

# 2020-10-06T11:26:19 update

# 2020-10-21T13:32:43 update

# 2020-12-14T18:18:36 update

# 2020-12-23T17:15:03 update

# 2021-01-25T16:29:00 update

# 2021-02-23T11:23:50 update

# 2021-03-19T12:21:19 update

# 2021-07-29T18:48:25 update

# 2021-08-25T12:46:58 update

# 2021-09-09T16:27:13 update

# 2021-12-16T12:05:30 update

# 2022-05-07T14:05:12 update

# 2022-07-18T20:52:29 update

# 2022-07-31T18:42:26 update

# 2022-09-09T13:10:08 update

# 2023-01-04T15:16:57 update

# 2023-01-17T14:49:04 update

# 2023-02-15T13:51:30 update

# 2023-03-08T09:15:53 update

# 2023-03-23T16:32:20 update

# 2023-03-28T09:32:01 update

# 2023-05-05T17:28:22 update

# 2023-06-01T08:13:52 update

# 2023-06-20T09:58:10 update

# 2023-07-04T16:14:34 update

# 2023-07-17T20:49:40 update

# 2023-12-26T11:49:18 update

# 2024-05-27T11:00:06 update

# 2024-07-04T08:53:03 update

# 2024-07-18T16:19:02 update

# 2024-08-07T09:35:35 update

# 2024-08-22T14:32:14 update

# 2025-05-20T14:19:23 update

# 2025-07-17T17:54:48 update

# 2025-07-28T13:06:30 update

# 2025-12-22T19:05:25 update

# 2026-01-08T18:43:02 update

# 2026-01-12T16:53:28 update

# 2026-04-16T16:58:23 update
