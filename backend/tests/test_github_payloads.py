"""T027 [US2] — GitHub issue payload tests (FR-013, Decision 15).

RED until T031 creates backend/tools/github.py.
Interface imposed on T031: ``build_issue_payload(task: Task) -> dict`` returning
``{"title", "body", "labels"}`` — body includes the description and acceptance criteria,
labels are exactly the required v1 set.
"""


def test_issue_payload_has_title_body_and_required_labels():
    from agents.schemas import Task
    from tools.github import build_issue_payload

    task = Task(
        title="Build wireframes",
        description="Three onboarding screens",
        milestone="Design",
        suggested_owner=None,
        priority="high",
        acceptance_criteria=["3 screens reviewed", "a11y checked"],
        dependencies=[],
    )
    payload = build_issue_payload(task)

    assert payload["title"] == "Build wireframes"
    assert "Three onboarding screens" in payload["body"]  # description
    assert "3 screens reviewed" in payload["body"]  # acceptance criteria in body
    assert "a11y checked" in payload["body"]
    assert set(payload["labels"]) == {"flowpilot", "approved", "ai-generated", "mvp"}
