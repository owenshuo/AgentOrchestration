"""Task Scheduler - Priority-based task queuing and dispatch."""

from dataclasses import dataclass
import heapq
import time
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


TERMINAL_LIFECYCLE_STATES = {"cancelled", "completed", "deleted", "failed"}


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def remove_matching(self, predicate: Callable[[Any], bool]) -> int:
        retained = []
        removed = 0
        for entry in self._queue:
            if predicate(entry[2]):
                removed += 1
            else:
                retained.append(entry)
        if removed:
            self._queue = retained
            heapq.heapify(self._queue)
        return removed

    def __len__(self) -> int:
        return len(self._queue)


@dataclass(frozen=True)
class ScheduledTask:
    task: Dict[str, Any]
    run_at: float
    queue: str
    priority: int


@dataclass(frozen=True)
class WorkflowDeletionTombstone:
    workflow_id: str
    revision: int
    attempt: int
    lifecycle_state: str
    deleted_at: float


class TaskScheduler:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, ScheduledTask] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._workflow_deletions: Dict[str, WorkflowDeletionTombstone] = {}
        self._audit_events: List[Dict[str, Any]] = []
        self._max_retries = 3
        self._clock = clock

    @property
    def audit_events(self) -> List[Dict[str, Any]]:
        return list(self._audit_events)

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> Optional[str]:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = self._clock()
        task["retries"] = task.get("retries", 0)
        task["queue"] = queue
        task["priority"] = priority

        if self._reject_stale_poll_transition(task, "enqueue"):
            return None

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> Optional[str]:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = self._clock()
        task["retries"] = task.get("retries", 0)
        task["queue"] = queue
        task["priority"] = priority

        if self._reject_stale_poll_transition(task, "schedule"):
            return None

        self._scheduled[task_id] = ScheduledTask(
            task=task,
            run_at=self._clock() + delay,
            queue=queue,
            priority=priority,
        )
        return task_id

    def mark_workflow_deleted(
        self,
        workflow_id: str,
        revision: int = 0,
        attempt: int = 0,
        lifecycle_state: str = "deleted",
    ) -> int:
        existing = self._workflow_deletions.get(workflow_id)
        if existing and (
            existing.revision,
            existing.attempt,
        ) > (revision, attempt):
            tombstone = existing
        else:
            tombstone = WorkflowDeletionTombstone(
                workflow_id=workflow_id,
                revision=revision,
                attempt=attempt,
                lifecycle_state=lifecycle_state,
                deleted_at=self._clock(),
            )
            self._workflow_deletions[workflow_id] = tombstone
        removed = self._remove_stale_poll_transitions(tombstone)
        self._audit_events.append(
            {
                "decision": "workflow_deleted",
                "workflow_id": workflow_id,
                "revision": tombstone.revision,
                "attempt": tombstone.attempt,
                "lifecycle_state": tombstone.lifecycle_state,
                "removed_poll_tasks": removed,
            }
        )
        return removed

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        now = self._clock()
        expired = [
            tid for tid, scheduled in self._scheduled.items()
            if scheduled.run_at <= now
        ]
        for tid in expired:
            scheduled = self._scheduled.pop(tid)
            if self._reject_stale_poll_transition(scheduled.task, "dequeue"):
                continue
            if scheduled.queue not in self._queues:
                self._queues[scheduled.queue] = PriorityQueue()
            self._queues[scheduled.queue].push(
                scheduled.task,
                scheduled.priority,
            )

        if queue in self._queues and len(self._queues[queue]) > 0:
            while len(self._queues[queue]) > 0:
                task = self._queues[queue].pop()
                if not task:
                    continue
                if self._reject_stale_poll_transition(task, "dequeue"):
                    continue
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.get(task_id)
        if task and self._reject_stale_poll_transition(task, "complete"):
            self._in_flight.pop(task_id, None)
            return False
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            if self._reject_stale_poll_transition(task, "retry"):
                return False
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                task_id = self.enqueue(
                    task,
                    queue,
                    priority=task.get("priority", 0),
                )
                return task_id is not None
        return False

    def _remove_stale_poll_transitions(
        self,
        tombstone: WorkflowDeletionTombstone,
    ) -> int:
        removed = 0
        for task_queue in self._queues.values():
            removed += task_queue.remove_matching(
                lambda task: self._is_stale_poll_transition(task, tombstone)
            )
        for task_id, scheduled in list(self._scheduled.items()):
            if self._is_stale_poll_transition(scheduled.task, tombstone):
                self._scheduled.pop(task_id, None)
                removed += 1
        for task_id, task in list(self._in_flight.items()):
            if self._is_stale_poll_transition(task, tombstone):
                self._in_flight.pop(task_id, None)
                removed += 1
        return removed

    def _reject_stale_poll_transition(self, task: Dict, action: str) -> bool:
        workflow_id = task.get("workflow_id")
        tombstone = self._workflow_deletions.get(workflow_id)
        if not tombstone:
            return False
        if not self._is_stale_poll_transition(task, tombstone):
            return False

        self._audit_events.append(
            {
                "decision": "rejected",
                "reason": "workflow_deleted",
                "action": action,
                "task_id": task.get("id"),
                "workflow_id": workflow_id,
                "workflow_revision": int(task.get("workflow_revision", 0)),
                "workflow_attempt": int(task.get("workflow_attempt", 0)),
                "lifecycle_state": task.get("lifecycle_state", "unknown"),
                "deleted_revision": tombstone.revision,
                "deleted_attempt": tombstone.attempt,
                "deleted_lifecycle_state": tombstone.lifecycle_state,
            }
        )
        return True

    def _is_stale_poll_transition(
        self,
        task: Dict,
        tombstone: WorkflowDeletionTombstone,
    ) -> bool:
        if not self._is_poll_transition(task):
            return False
        if task.get("workflow_id") != tombstone.workflow_id:
            return False
        if task.get("lifecycle_state") in TERMINAL_LIFECYCLE_STATES:
            return False

        task_revision = int(task.get("workflow_revision", 0))
        task_attempt = int(task.get("workflow_attempt", 0))
        if task_revision < tombstone.revision:
            return True
        if task_revision > tombstone.revision:
            return False
        return task_attempt <= tombstone.attempt

    @staticmethod
    def _is_poll_transition(task: Dict) -> bool:
        return task.get("type") == "poll" or task.get("transition") == "poll"

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
