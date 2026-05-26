"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Deque, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)

TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._reducer_errors: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._task_revisions: Dict[str, int] = {}
        self._task_attempts: Dict[str, int] = {}
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    @property
    def reducer_errors(self) -> List[Dict[str, Any]]:
        return [dict(error) for error in self._reducer_errors]

    def reducer_error_report(self) -> Dict[str, Any]:
        errors = self.reducer_errors
        return {
            "total": len(errors),
            "by_reason": dict(Counter(error["reason"] for error in errors)),
            "by_attempted_state": dict(
                Counter(error["attempted_state"] for error in errors)
            ),
            "recent": errors,
        }

    def _record_reducer_error(
        self,
        task: Dict[str, Any],
        reason: str,
        attempted_state: str,
        expected_revision: Optional[int],
        actual_revision: int,
        expected_attempt: Optional[int],
        actual_attempt: int,
    ) -> None:
        error = {
            "task_id": task["id"],
            "reason": reason,
            "attempted_state": attempted_state,
            "current_state": task.get("state", "queued"),
            "expected_revision": expected_revision,
            "actual_revision": actual_revision,
            "expected_attempt": expected_attempt,
            "actual_attempt": actual_attempt,
        }
        self._reducer_errors.append(error)
        logger.warning(
            "Rejected task reducer transition",
            extra={"reducer_error": error},
        )

    def _reduce_task_state(
        self,
        task: Dict[str, Any],
        next_state: str,
        expected_revision: Optional[int] = None,
        expected_attempt: Optional[int] = None,
    ) -> bool:
        task_id = task["id"]
        current_state = task.get("state", "queued")
        actual_revision = self._task_revisions.get(
            task_id,
            int(task.get("revision", 0)),
        )
        actual_attempt = self._task_attempts.get(
            task_id,
            int(task.get("attempt", 0)),
        )

        if (
            expected_revision is not None
            and expected_revision != actual_revision
        ):
            self._record_reducer_error(
                task,
                "stale_revision",
                next_state,
                expected_revision,
                actual_revision,
                expected_attempt,
                actual_attempt,
            )
            return False

        if expected_attempt is not None and expected_attempt != actual_attempt:
            self._record_reducer_error(
                task,
                "stale_attempt",
                next_state,
                expected_revision,
                actual_revision,
                expected_attempt,
                actual_attempt,
            )
            return False

        if (
            current_state in TERMINAL_TASK_STATES
            and current_state != next_state
        ):
            self._record_reducer_error(
                task,
                "terminal_state",
                next_state,
                expected_revision,
                actual_revision,
                expected_attempt,
                actual_attempt,
            )
            return False

        revision = actual_revision + 1
        task["state"] = next_state
        task["revision"] = revision
        task["attempt"] = actual_attempt
        self._task_revisions[task_id] = revision
        self._task_attempts[task_id] = actual_attempt
        return True

    def _begin_task_attempt(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        attempt = self._task_attempts.get(task_id, int(task.get("attempt", 0)))
        attempt += 1
        task["attempt"] = attempt
        self._task_attempts[task_id] = attempt

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestration engine stopped")

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task["target_agent"]
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        task.setdefault("state", "queued")
        task.setdefault("revision", 0)
        task.setdefault("attempt", 0)
        self._task_revisions.setdefault(task_id, int(task["revision"]))
        self._task_attempts.setdefault(task_id, int(task["attempt"]))

        for hook in self._hooks["pre_execute"]:
            await hook(task)

        try:
            agent = self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            self._begin_task_attempt(task)
            expected_attempt = task["attempt"]
            if not self._reduce_task_state(
                task,
                "running",
                expected_revision=task["revision"],
                expected_attempt=expected_attempt,
            ):
                return

            self.registry.update_status(agent_id, AgentStatus.RUNNING)
            result = await asyncio.wait_for(
                self._run_agent_task(agent, task),
                timeout=self.agent_timeout,
            )
            if not self._reduce_task_state(
                task,
                "completed",
                expected_revision=task["revision"],
                expected_attempt=expected_attempt,
            ):
                return
            self.registry.update_status(agent_id, AgentStatus.PAUSED)

            for hook in self._hooks["post_execute"]:
                await hook(task, result)

            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            self._reduce_task_state(
                task,
                "failed",
                expected_revision=task.get("revision"),
                expected_attempt=task.get("attempt"),
            )
            logger.error(f"Task {task_id} failed: {e}")
            for hook in self._hooks["on_error"]:
                await hook(task, e)

    async def _run_agent_task(self, agent: Dict, task: Dict) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._execute_in_thread,
            agent,
            task,
        )

    def _execute_in_thread(self, agent: Dict, task: Dict) -> Any:
        return {
            "status": "completed",
            "output": f"Task {task['id']} processed by {agent['name']}",
        }

# 2019-04-24T14:55:39 update

# 2019-05-01T16:01:52 update

# 2019-05-27T19:55:55 update

# 2019-06-02T09:38:08 update

# 2019-07-10T15:36:32 update

# 2019-07-22T11:36:40 update

# 2019-08-28T10:50:39 update

# 2019-08-30T14:21:57 update

# 2019-09-12T18:46:28 update

# 2019-10-02T09:55:59 update

# 2019-10-03T16:01:13 update

# 2019-12-03T13:07:37 update

# 2020-01-10T13:47:02 update

# 2020-01-31T13:14:49 update

# 2020-03-11T08:03:44 update

# 2020-03-31T15:51:14 update

# 2020-04-10T11:21:15 update

# 2020-06-08T09:31:33 update

# 2020-06-16T20:32:00 update

# 2020-07-21T18:48:01 update

# 2020-09-29T15:16:08 update

# 2020-11-18T14:09:09 update

# 2020-11-26T18:02:40 update

# 2021-01-07T11:18:24 update

# 2021-04-05T15:49:29 update

# 2021-04-27T11:58:27 update

# 2021-05-17T14:54:17 update

# 2021-06-07T11:46:07 update

# 2021-08-31T14:55:54 update

# 2021-09-10T17:29:34 update

# 2021-09-14T10:27:30 update

# 2021-10-06T14:04:05 update

# 2022-03-15T18:11:19 update

# 2022-09-15T18:32:09 update

# 2022-11-17T08:15:16 update

# 2023-02-17T12:24:53 update

# 2023-04-25T14:26:37 update

# 2023-05-22T09:03:39 update

# 2023-09-06T20:26:58 update

# 2023-11-28T17:54:23 update

# 2023-12-27T15:38:11 update

# 2024-03-12T20:10:32 update

# 2024-04-04T20:43:06 update

# 2024-05-27T12:23:51 update

# 2024-05-27T16:42:42 update

# 2024-07-23T13:27:05 update

# 2024-07-24T19:24:13 update

# 2024-11-03T18:25:58 update

# 2025-04-23T20:03:19 update

# 2026-02-16T17:12:09 update

# 2026-03-12T11:33:28 update
