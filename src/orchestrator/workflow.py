"""Workflow Manager — Defines and executes multi-step agent workflows."""

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowValidationError(ValueError):
    """Raised when policy injection leaves a workflow graph invalid."""


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        step_id: Optional[str] = None,
        requires_guard: bool = True,
        is_guard: bool = False,
        protects_step_id: Optional[str] = None,
    ):
        self.id = step_id or str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
        self.requires_guard = requires_guard
        self.is_guard = is_guard
        self.protects_step_id = protects_step_id


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


def guard_handler() -> bool:
    return True


class WorkflowPolicyInjector:
    """Injects automatic guard nodes and validates the resulting graph."""

    def inject_guards(self, workflow: Workflow) -> Workflow:
        injected_steps: List[WorkflowStep] = []
        for step in workflow.steps:
            if step.is_guard or not step.requires_guard:
                injected_steps.append(step)
                continue

            guard = WorkflowStep(
                name=f"policy_guard:{step.name}",
                handler=guard_handler,
                requires_guard=False,
                is_guard=True,
                protects_step_id=step.id,
            )
            injected_steps.extend([guard, step])

        workflow.steps = injected_steps
        workflow._step_map = {step.id: step for step in workflow.steps}
        return workflow

    def validate(self, workflow: Workflow) -> None:
        seen: Set[str] = set()
        guarded_step_ids: Set[str] = set()

        for step in workflow.steps:
            if step.id in seen:
                raise WorkflowValidationError(
                    f"duplicate workflow step id rejected: {step.id}"
                )
            seen.add(step.id)

            if step.status is not StepStatus.PENDING:
                raise WorkflowValidationError(
                    f"stale workflow step rejected during policy injection: "
                    f"{step.id}"
                )

            if step.is_guard:
                if not step.protects_step_id:
                    raise WorkflowValidationError(
                        f"guard step {step.id} does not protect a step"
                    )
                guarded_step_ids.add(step.protects_step_id)

        missing_guards = [
            step.id
            for step in workflow.steps
            if step.requires_guard
            and not step.is_guard
            and step.id not in guarded_step_ids
        ]
        if missing_guards:
            raise WorkflowValidationError(
                "workflow policy guard missing for steps: "
                f"{', '.join(sorted(missing_guards))}"
            )

    def inject_and_validate(self, workflow: Workflow) -> Workflow:
        self.inject_guards(workflow)
        self.validate(workflow)
        return workflow


class WorkflowManager:
    def __init__(
        self,
        policy_injector: Optional[WorkflowPolicyInjector] = None,
    ):
        self._workflows: Dict[str, Workflow] = {}
        self.policy_injector = policy_injector or WorkflowPolicyInjector()
        self.audit_records: List[Dict[str, str]] = []

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self.register_workflow(workflow)
        return workflow

    def register_workflow(self, workflow: Workflow) -> Workflow:
        previous = self._workflows.get(workflow.id)
        try:
            self.policy_injector.inject_and_validate(workflow)
        except WorkflowValidationError as error:
            self._record_audit(
                workflow.id,
                "policy_graph_rejected",
                str(error),
            )
            if previous is None:
                self._workflows.pop(workflow.id, None)
            else:
                self._workflows[workflow.id] = previous
            raise

        self._workflows[workflow.id] = workflow
        self._record_audit(
            workflow.id,
            "policy_graph_accepted",
            "automatic guard nodes validated",
        )
        return workflow

    def _record_audit(self, workflow_id: str, event: str, reason: str) -> None:
        self.audit_records.append(
            {"workflow_id": workflow_id, "event": event, "reason": reason}
        )
        logger.info("workflow policy decision: %s", event)

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

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
