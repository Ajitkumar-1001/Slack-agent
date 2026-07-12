"""T016 [US1] — approval-card Block Kit tests (FR-006/FR-009, SC-004).

RED until T023 creates backend/slack/blocks.py.

Interface imposed on T023:
- ``render_approval_card(*, proposal_id: str, plan: ProjectPlan, action_summary: str) -> list[dict]``
  returning a Block Kit blocks list. Each button carries a stable ``action_id`` and a
  ``value`` containing the ``proposal_id``.
"""
import json


def test_approval_card_has_required_fields_and_action_ids(valid_plan_dict):
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, action_summary="Create 1 GitHub issue"
    )
    assert isinstance(blocks, list)
    text = json.dumps(blocks)

    # required content: title, objective, timeline, proposed external actions
    assert "Onboarding Redesign" in text
    assert "redesigned onboarding flow" in text
    assert "4 weeks" in text
    assert "Create 1 GitHub issue" in text

    # top-3 risks surfaced; the 4th (low-severity "Unclear scope") is excluded under
    # either "first 3" or "top 3 by severity" — it is both last in the list and lowest severity
    assert "Dep on Auth API" in text  # critical
    assert "No owner" in text  # high
    assert "Unclear scope" not in text  # low, must be excluded from the top-3

    # three stable action IDs, each carrying the proposal_id
    for action_id in ("approve_plan", "edit_plan", "reject_plan"):
        assert action_id in text
    assert "prop-123" in text


def test_approval_card_includes_target_system_selector_and_encodes_approve_value(valid_plan_dict):
    """T007 [US1] — target-system selector (FR-101; contracts/block-kit.md).

    RED until T010 extends render_approval_card with the GitHub/Jira/Both static_select and
    changes the Approve button's value to "{proposal_id}|{target_system}" (Edit/Reject unchanged).
    """
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, action_summary="Create 1 Jira ticket", target_system="jira"
    )

    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]

    select = next(el for el in elements if el.get("action_id") == "select_target_system")
    assert select["type"] == "static_select"
    assert {opt["value"] for opt in select["options"]} == {"github", "jira", "both"}
    assert select["initial_option"]["value"] == "jira"

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-123|jira"

    # Edit Plan / Reject are unaffected by the target-system choice — they create zero artifacts
    edit = next(el for el in elements if el.get("action_id") == "edit_plan")
    reject = next(el for el in elements if el.get("action_id") == "reject_plan")
    assert edit["value"] == "prop-123"
    assert reject["value"] == "prop-123"


def test_approval_card_defaults_target_system_selector_to_github(valid_plan_dict):
    """T007 [US1] — AC-105: no target_system passed -> defaults to settings.default_target_system
    ("github" out of the box), so a no-Jira deployment's card looks the same as v1's."""
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(proposal_id="prop-1", plan=plan, action_summary="Create 1 GitHub issue")

    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]
    select = next(el for el in elements if el.get("action_id") == "select_target_system")
    assert select["initial_option"]["value"] == "github"

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-1|github"


def test_stakeholder_summary_includes_links_risks_and_partial_breakdown():
    """T030 [US2] — stakeholder-summary payload (FR-016/FR-017), updated for T023's
    created_by_system/failed_by_system signature (FR-105; superseded the old flat
    created/failed interface this test originally exercised).
    """
    from slack.blocks import render_stakeholder_summary

    blocks = render_stakeholder_summary(
        project_name="Onboarding Redesign",
        created_by_system={"github": [("Build wireframes", "https://github.com/x/y/issues/1")]},
        failed_by_system={"github": ["Set up CI"]},
        open_risks=["No owner (high)"],
        next_steps="Retry the failed task after assigning an owner.",
    )
    assert isinstance(blocks, list)
    text = json.dumps(blocks)

    assert "Onboarding Redesign" in text  # project name
    assert "https://github.com/x/y/issues/1" in text  # created-issue link on success
    assert "Set up CI" in text  # failed task in the succeeded/failed breakdown
    assert "No owner" in text  # open risks
    assert "Retry the failed task" in text  # next steps


def _section_texts(blocks):
    return [b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b]


def test_stakeholder_summary_groups_created_by_system():
    """T021 [US3] — per-system summary grouping (FR-105; contracts/block-kit.md).

    RED until T023 changes render_stakeholder_summary's signature from one flat created/failed
    list to created_by_system/failed_by_system dicts, rendering one section per system.
    """
    from slack.blocks import render_stakeholder_summary

    blocks = render_stakeholder_summary(
        project_name="Onboarding Redesign",
        created_by_system={
            "github": [("Build wireframes", "https://github.com/x/y/issues/1")],
            "jira": [("Build wireframes", "https://example.atlassian.net/browse/PROJ-1")],
        },
        failed_by_system={"github": [], "jira": []},
        open_risks=[],
        next_steps="Track the created issues to completion.",
    )
    texts = _section_texts(blocks)

    github_section = next(t for t in texts if "*GitHub:*" in t)
    jira_section = next(t for t in texts if "*Jira:*" in t)
    assert "https://github.com/x/y/issues/1" in github_section
    assert "https://example.atlassian.net/browse/PROJ-1" in jira_section

    # each system's created items must land in its own section, not a shared flat list
    assert github_section != jira_section
    assert "https://example.atlassian.net/browse/PROJ-1" not in github_section
    assert "https://github.com/x/y/issues/1" not in jira_section


def test_stakeholder_summary_renders_per_system_partial_failure_breakdown():
    """T022 [US3] — partial-failure breakdown (AC-104; contracts/block-kit.md).

    RED until T023. When Jira fails for a task but GitHub succeeds for all of its tasks, the
    summary must show a per-system succeeded/failed breakdown -- not one aggregate pass/fail
    result for the whole run.
    """
    from slack.blocks import render_stakeholder_summary

    blocks = render_stakeholder_summary(
        project_name="Onboarding Redesign",
        created_by_system={
            "github": [
                ("Build wireframes", "https://github.com/x/y/issues/1"),
                ("Write copy", "https://github.com/x/y/issues/2"),
            ],
            "jira": [("Build wireframes", "https://example.atlassian.net/browse/PROJ-1")],
        },
        failed_by_system={"github": [], "jira": ["Write copy"]},
        open_risks=[],
        next_steps="Retry the failed Jira task once resolved.",
    )
    texts = _section_texts(blocks)

    github_lines = [t for t in texts if "*GitHub:*" in t]
    jira_lines = [t for t in texts if "*Jira:*" in t]
    assert github_lines and jira_lines
    assert "Write copy" in "\n".join(texts)  # the failed task surfaces in jira's breakdown

    # a genuine per-system breakdown: github (all succeeded) and jira (one failure) must be
    # independently visible, not collapsed into one aggregate pass/fail line for the run
    assert not any("fail" in t.lower() for t in github_lines)
    assert any("fail" in t.lower() for t in jira_lines)

