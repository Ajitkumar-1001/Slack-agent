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


def test_stakeholder_summary_includes_links_risks_and_partial_breakdown():
    """T030 [US2] — stakeholder-summary payload (FR-016/FR-017). RED until T034 adds
    render_stakeholder_summary to slack/blocks.py.

    Interface imposed on T034: ``render_stakeholder_summary(*, project_name, created, failed,
    open_risks, next_steps) -> list[dict]`` where ``created`` is ``list[(title, url)]`` and
    ``failed`` is ``list[title]``.
    """
    from slack.blocks import render_stakeholder_summary

    blocks = render_stakeholder_summary(
        project_name="Onboarding Redesign",
        created=[("Build wireframes", "https://github.com/x/y/issues/1")],
        failed=["Set up CI"],
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

