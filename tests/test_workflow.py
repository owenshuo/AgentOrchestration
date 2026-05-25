import pytest

from src.orchestrator.workflow import (
    WorkflowManager,
    WorkflowStep,
    WorkflowValidationError,
)


def noop_handler():
    return "ok"


class TestWorkflowParameterAliases:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_create_workflow_rejects_duplicate_parameter_aliases(self):
        with pytest.raises(
            WorkflowValidationError,
            match="Duplicate workflow parameter alias",
        ):
            self.manager.create_workflow(
                "duplicate-alias-workflow",
                input_parameters=[
                    {"name": "customer_id", "alias": "customer"},
                    {"name": "account_id", "aliases": ["Customer"]},
                ],
            )

        assert self.manager.list_workflows() == []

    def test_create_workflow_accepts_unique_aliases_and_records_audit(self):
        workflow = self.manager.create_workflow(
            "valid-workflow",
            input_parameters=[
                {"name": "customer_id", "alias": "customer"},
                {"name": "account_id", "aliases": ["account"]},
            ],
        )

        assert self.manager.get_workflow(workflow.id) is workflow
        assert workflow.validation_audit == [
            {
                "scope": "workflow",
                "decision": "accepted",
                "reason": "unique_parameter_aliases",
            }
        ]

    def test_add_step_rejects_duplicate_aliases_without_mutating_workflow(
        self,
    ):
        workflow = self.manager.create_workflow("valid-workflow")
        step = WorkflowStep(
            "load-customer",
            noop_handler,
            input_parameters=[
                {"name": "customer_id", "alias": "customer"},
                {"name": "legacy_customer_id", "aliases": ["customer"]},
            ],
        )

        with pytest.raises(WorkflowValidationError):
            workflow.add_step(step)

        assert workflow.steps == []
        assert workflow.get_step(step.id) is None
        assert workflow.status.value == "pending"

    def test_add_step_accepts_unique_input_aliases_and_preserves_execution(
        self,
    ):
        workflow = self.manager.create_workflow("valid-workflow")
        workflow.add_step(
            WorkflowStep(
                "load-customer",
                noop_handler,
                input_parameters=[
                    {"name": "customer_id", "aliases": ["customer"]}
                ],
            )
        )

        assert self.manager.execute_workflow(workflow.id)
        assert workflow.validation_audit[-1]["decision"] == "accepted"
