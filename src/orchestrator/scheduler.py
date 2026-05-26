"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from src.agent.registry import AgentRegistry, AgentStatus


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

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self, registry: Optional[AgentRegistry] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._deferred: Dict[str, Dict] = {}
        self._resolution_cache: Dict[str, Dict[str, Any]] = {}
        self._retired_agents: Set[str] = set()
        self._audit_events: List[Dict[str, Any]] = []
        self._max_retries = 3
        self.registry: Optional[AgentRegistry] = None
        if registry:
            self.bind_registry(registry)

    def bind_registry(self, registry: AgentRegistry) -> None:
        self.registry = registry
        registry.subscribe_changes(self.handle_registry_change)
        self._resolution_cache.clear()

    def handle_registry_change(self, event: Dict[str, Any]) -> None:
        action = event.get("action")
        if action in {"retired", "deregistered", "status_changed"}:
            agent_id = event.get("agent_id")
            agent_type = event.get("agent_type")
            if agent_id and action in {"retired", "deregistered"}:
                self._retired_agents.add(agent_id)
            if agent_type:
                self._resolution_cache.pop(agent_type, None)
            self._audit("handler_cache_invalidated", None, event)

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def _target_handler_type(self, task: Dict[str, Any]) -> Optional[str]:
        return (
            task.get("handler_type")
            or task.get("agent_type")
            or task.get("handler")
        )

    def _resolve_handler(
        self,
        task: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not self.registry:
            return None
        handler_type = self._target_handler_type(task)
        if not handler_type:
            return None
        cached = self._resolution_cache.get(handler_type)
        if (
            cached
            and cached.get("registry_revision") == self.registry.revision
        ):
            agent = self.registry.get(cached["agent_id"])
            if agent and agent["status"] == AgentStatus.RUNNING.value:
                return agent
            self._resolution_cache.pop(handler_type, None)

        group = handler_type.split(".")[0]
        candidates = [
            agent
            for agent in self.registry.list(
                status=AgentStatus.RUNNING,
                group=group,
            )
            if (
                agent["type"] == handler_type
                and agent["id"] not in self._retired_agents
            )
        ]
        if not candidates:
            return None

        agent = sorted(candidates, key=lambda item: item["updated_at"])[0]
        self._resolution_cache[handler_type] = {
            "agent_id": agent["id"],
            "registry_revision": self.registry.revision,
        }
        return agent

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                handler_type = self._target_handler_type(task)
                if self.registry and handler_type:
                    handler = self._resolve_handler(task)
                    if not handler:
                        task["deferred_reason"] = (
                            "handler_retired_or_unavailable"
                        )
                        task["deferred_at"] = time.time()
                        task["registry_revision"] = self.registry.revision
                        self._deferred[task["id"]] = task
                        self._audit(
                            "task_deferred",
                            task,
                            {"handler_type": handler_type},
                        )
                        return None
                    task["resolved_agent_id"] = handler["id"]
                    task["registry_revision"] = self.registry.revision
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def deferred_tasks(self) -> List[Dict[str, Any]]:
        return [dict(task) for task in self._deferred.values()]

    def audit_report(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def _audit(
        self,
        action: str,
        task: Optional[Dict[str, Any]],
        details: Dict[str, Any],
    ) -> None:
        event = {
            "action": action,
            "task_id": task.get("id") if task else None,
            "details": {
                key: value
                for key, value in details.items()
                if key not in {"payload", "config", "secret", "token"}
            },
            "timestamp": time.time(),
        }
        self._audit_events.append(event)

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
