"""T005 [US1] — Jira ticket payload tests (FR-102; contracts/tool-adapters.md).

Mirrors test_github_payloads.py. Interface imposed on T009 (backend/tools/jira.py):
``build_ticket_payload(task: Task) -> dict`` returning a Jira Cloud REST v3 issue-create payload
shaped ``{"fields": {"project", "summary", "description", "issuetype", "priority", "labels"}}`` —
description includes the task description and acceptance criteria, labels are exactly the
required v1 set (the idempotency marker label is added later by create_ticket_idempotent, not
here — see data-model.md).
"""


def test_ticket_payload_has_required_fields_and_labels(monkeypatch):
    from agents.schemas import Task
    from app.config import settings
    from tools.jira import build_ticket_payload

    monkeypatch.setattr(settings, "jira_project_key", "PROJ")

    task = Task(
        title="Build wireframes",
        description="Three onboarding screens",
        milestone="Design",
        suggested_owner=None,
        priority="high",
        acceptance_criteria=["3 screens reviewed", "a11y checked"],
        dependencies=[],
    )
    payload = build_ticket_payload(task)
    fields = payload["fields"]

    assert fields["summary"] == "Build wireframes"
    assert "Three onboarding screens" in fields["description"]  # description
    assert "3 screens reviewed" in fields["description"]  # acceptance criteria in description
    assert "a11y checked" in fields["description"]
    assert fields["issuetype"] == {"name": "Task"}
    assert fields["project"] == {"key": "PROJ"}
    assert fields["priority"] == {"name": "High"}
    assert set(fields["labels"]) == {"flowpilot", "approved", "ai-generated", "mvp"}


def test_priority_mapping_covers_all_task_priorities():
    """research.md Decision 5 — fixed 3-way map onto Jira's default priority scheme."""
    from agents.schemas import Task
    from tools.jira import build_ticket_payload

    expected = {"low": "Low", "medium": "Medium", "high": "High"}
    for task_priority, jira_priority in expected.items():
        task = Task(
            title="T", description="d", milestone=None, suggested_owner=None,
            priority=task_priority, acceptance_criteria=[], dependencies=[],
        )
        assert build_ticket_payload(task)["fields"]["priority"] == {"name": jira_priority}
