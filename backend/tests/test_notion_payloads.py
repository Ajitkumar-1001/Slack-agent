"""T003 [P] [US1] — Notion brief payload tests (FR-202; contracts/tool-adapters.md).

RED until T009 creates backend/tools/notion.py.
Interface imposed on T009: ``build_brief_payload(proposal_id: str, plan: ProjectPlan,
links: list[tuple[str, str, str]], idempotency_key: str) -> dict`` returning a Notion
``POST /v1/pages`` payload (see data-model.md) — the idempotency marker lives in the page
title (research.md Decision 2), and the body links to every (system, title, url) triple
passed in, GitHub before Jira (FR-202).
"""
import json


def _plan():
    from agents.schemas import Milestone, ProjectPlan, Risk, Task

    return ProjectPlan(
        project_name="Launch v2",
        objective="Ship the v2 onboarding flow",
        timeline="Q3 2026",
        milestones=[
            Milestone(
                title="Design done",
                description="Wireframes approved",
                due_date="2026-08-01",
                success_criteria=["3 screens reviewed"],
            )
        ],
        tasks=[
            Task(
                title="Build wireframes",
                description="Three onboarding screens",
                milestone="Design done",
                suggested_owner="alice",
                priority="high",
                acceptance_criteria=["3 screens reviewed"],
                dependencies=[],
            )
        ],
        risks=[
            Risk(
                title="Design delay",
                severity="medium",
                explanation="Designer is on another project",
                mitigation="Pair with a second designer",
            )
        ],
        dependencies=[],
        assumptions=[],
        evidence_summary=[],
    )


def test_brief_payload_title_contains_marker_and_project_name(monkeypatch):
    from app.config import settings
    from tools.notion import build_brief_payload

    monkeypatch.setattr(settings, "notion_parent_page_id", "parent-page-id")

    idempotency_key = "proposal-1:notion:create_project_brief"
    payload = build_brief_payload(
        proposal_id="proposal-1", plan=_plan(), links=[], idempotency_key=idempotency_key
    )

    title_text = json.dumps(payload["properties"]["title"])
    assert idempotency_key in title_text
    assert "Launch v2" in title_text
    assert payload["parent"] == {"page_id": "parent-page-id"}


def test_brief_payload_body_includes_plan_content_and_links_ordered_github_before_jira():
    from tools.notion import build_brief_payload

    links = [
        ("jira", "Build wireframes", "https://jira.example.com/browse/PROJ-1"),
        ("github", "Build wireframes", "https://github.com/org/repo/issues/1"),
    ]
    payload = build_brief_payload(
        proposal_id="proposal-1",
        plan=_plan(),
        links=links,
        idempotency_key="proposal-1:notion:create_project_brief",
    )

    body_text = json.dumps(payload["children"])
    assert "Ship the v2 onboarding flow" in body_text  # objective
    assert "Design done" in body_text  # milestone title
    assert "Build wireframes" in body_text  # task title
    assert "alice" in body_text  # suggested owner
    assert "Design delay" in body_text  # risk title
    assert "Pair with a second designer" in body_text  # risk mitigation

    github_pos = body_text.index("https://github.com/org/repo/issues/1")
    jira_pos = body_text.index("https://jira.example.com/browse/PROJ-1")
    assert github_pos < jira_pos  # FR-202: GitHub entries before Jira entries
