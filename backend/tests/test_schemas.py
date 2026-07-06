"""T013 [US1] — ProjectPlan schema validation tests.

RED until T019 creates backend/agents/schemas.py.
Imports are deferred into the test bodies so the suite stays collectable
(a missing module fails the test cleanly rather than erroring collection).
"""
import pytest


def test_valid_project_plan_validates(valid_plan_dict):
    from agents.schemas import ProjectPlan

    plan = ProjectPlan(**valid_plan_dict)
    assert plan.project_name == "Onboarding Redesign"
    assert len(plan.milestones) == 1
    assert len(plan.tasks) == 1
    assert len(plan.risks) == 4
    assert plan.tasks[0].priority == "high"
    assert plan.evidence_summary == ["Thread references a Q3 launch commitment"]


def test_invalid_task_priority_fails():
    from pydantic import ValidationError

    from agents.schemas import Task

    with pytest.raises(ValidationError):
        Task(
            title="x",
            description="y",
            milestone=None,
            suggested_owner=None,
            priority="urgent",  # not in {low, medium, high}
            acceptance_criteria=[],
            dependencies=[],
        )


def test_invalid_risk_severity_fails():
    from pydantic import ValidationError

    from agents.schemas import Risk

    with pytest.raises(ValidationError):
        Risk(title="x", severity="extreme", explanation="y", mitigation="z")  # not a valid severity
