"""Workflow Manager — Defines and executes multi-step agent workflows."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self.lifecycle = "active"
        self.revision = 0
        self.poll_attempt = 0

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


@dataclass(frozen=True)
class WorkflowPollToken:
    workflow_id: str
    attempt: int
    revision: int


class WorkflowPollCoordinator:
    """Guards task poll transitions against stale workflow lifecycle state."""

    def __init__(
        self,
        workflows: Dict[str, Workflow],
        deleted_revisions: Dict[str, int],
    ):
        self._workflows = workflows
        self._deleted_revisions = deleted_revisions
        self.audit_records: List[Dict[str, Any]] = []

    def begin_poll(self, workflow_id: str) -> Optional[WorkflowPollToken]:
        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            self._record(
                "rejected",
                workflow_id,
                reason="workflow_deleted",
                revision=self._deleted_revisions.get(workflow_id),
            )
            return None
        if workflow.lifecycle != "active":
            self._record(
                "rejected",
                workflow_id,
                reason="workflow_not_active",
                revision=workflow.revision,
            )
            return None

        workflow.poll_attempt += 1
        token = WorkflowPollToken(
            workflow_id=workflow_id,
            attempt=workflow.poll_attempt,
            revision=workflow.revision,
        )
        self._record(
            "accepted",
            workflow_id,
            reason="poll_started",
            attempt=token.attempt,
            revision=token.revision,
        )
        return token

    def commit_poll(
        self,
        token: WorkflowPollToken,
        status: StepStatus,
    ) -> bool:
        workflow = self._workflows.get(token.workflow_id)
        if workflow is None:
            self._record(
                "rejected",
                token.workflow_id,
                reason="workflow_deleted",
                attempt=token.attempt,
                revision=self._deleted_revisions.get(token.workflow_id),
                token_revision=token.revision,
            )
            return False
        if workflow.lifecycle != "active":
            self._record(
                "rejected",
                token.workflow_id,
                reason="workflow_not_active",
                attempt=token.attempt,
                revision=workflow.revision,
                token_revision=token.revision,
            )
            return False
        if workflow.revision != token.revision:
            self._record(
                "rejected",
                token.workflow_id,
                reason="stale_revision",
                attempt=token.attempt,
                revision=workflow.revision,
                token_revision=token.revision,
            )
            return False
        if workflow.poll_attempt != token.attempt:
            self._record(
                "rejected",
                token.workflow_id,
                reason="stale_attempt",
                attempt=token.attempt,
                current_attempt=workflow.poll_attempt,
                revision=workflow.revision,
            )
            return False

        workflow.status = status
        workflow.revision += 1
        self._record(
            "accepted",
            token.workflow_id,
            reason="poll_committed",
            attempt=token.attempt,
            revision=workflow.revision,
        )
        return True

    def mark_deleted(self, workflow: Workflow) -> None:
        workflow.lifecycle = "deleted"
        workflow.revision += 1
        self._deleted_revisions[workflow.id] = workflow.revision
        self._record(
            "accepted",
            workflow.id,
            reason="workflow_deleted",
            revision=workflow.revision,
        )

    def _record(
        self,
        decision: str,
        workflow_id: str,
        **fields: Any,
    ) -> None:
        self.audit_records.append(
            {
                "decision": decision,
                "workflow_id": workflow_id,
                **fields,
            }
        )


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._deleted_workflow_revisions: Dict[str, int] = {}
        self.poll_coordinator = WorkflowPollCoordinator(
            self._workflows,
            self._deleted_workflow_revisions,
        )

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.pop(workflow_id, None)
        if workflow is None:
            return False
        self.poll_coordinator.mark_deleted(workflow)
        return True

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True

# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
