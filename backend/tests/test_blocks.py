"""T016 [US1] — approval-card Block Kit tests (FR-006/FR-009, SC-004).

RED until T023 creates backend/slack/blocks.py.

Interface imposed on T023:
- ``render_approval_card(*, proposal_id: str, plan: ProjectPlan, ...) -> list[dict]``
  returning a Block Kit blocks list. Each button carries a stable ``action_id`` and a
  ``value`` containing the ``proposal_id``. The proposed-actions text is derived from the
  plan's task count and the selected target system / Notion toggle (FR-009), not passed in.
"""
import json

import pytest


def _proposed_actions_text(blocks):
    return next(
        b["text"]["text"]
        for b in blocks
        if b.get("block_id", "").startswith("proposed_actions|")
    )


def test_approval_card_identical_regardless_of_drive_tagged_evidence_summary(valid_plan_dict):
    """T017 [US3] — non-interference regression (AC-305).

    render_approval_card never references evidence_summary — a Drive-grounded proposal's card
    must render byte-identical to a Slack-only proposal's for the same plan otherwise.
    """
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    slack_only = dict(valid_plan_dict)
    drive_grounded = dict(valid_plan_dict)
    drive_grounded["evidence_summary"] = [
        "[slack] Thread references a Q3 launch commitment",
        "[drive] Project charter excerpt",
    ]

    blocks_slack_only = render_approval_card(
        proposal_id="prop-123", plan=ProjectPlan(**slack_only)
    )
    blocks_drive_grounded = render_approval_card(
        proposal_id="prop-123", plan=ProjectPlan(**drive_grounded)
    )

    assert blocks_slack_only == blocks_drive_grounded


def test_approval_card_has_required_fields_and_action_ids(valid_plan_dict):
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(proposal_id="prop-123", plan=plan)
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

    Updated for 003-flowpilot-notion-integration T010: the Approve value grows a third
    {notion_flag} segment (contracts/block-kit.md), always present regardless of Notion config.
    """
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, target_system="jira"
    )

    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]

    select = next(el for el in elements if el.get("action_id") == "select_target_system")
    assert select["type"] == "static_select"
    assert {opt["value"] for opt in select["options"]} == {"github", "jira", "both"}
    assert select["initial_option"]["value"] == "jira"

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-123|jira|false"

    # Edit Plan / Reject are unaffected by the target-system choice — they create zero artifacts
    edit = next(el for el in elements if el.get("action_id") == "edit_plan")
    reject = next(el for el in elements if el.get("action_id") == "reject_plan")
    assert edit["value"] == "prop-123"
    assert reject["value"] == "prop-123"


def test_approval_card_defaults_target_system_selector_to_github(valid_plan_dict):
    """T007 [US1] — AC-105: no target_system passed -> defaults to settings.default_target_system
    ("github" out of the box), so a no-Jira deployment's card looks the same as v1's.

    Updated for 003-flowpilot-notion-integration T010: the Approve value grows a third
    {notion_flag} segment, defaulting to "false" (settings.default_notion_enabled)."""
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(proposal_id="prop-1", plan=plan)

    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]
    select = next(el for el in elements if el.get("action_id") == "select_target_system")
    assert select["initial_option"]["value"] == "github"

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-1|github|false"


def test_approval_card_includes_checked_notion_checkbox_and_encodes_flag_in_approve_value(
    monkeypatch, valid_plan_dict
):
    """T005 [US1] — Notion brief toggle, checked case (FR-201; contracts/block-kit.md).

    RED until T010 extends render_approval_card with the checkboxes element and the
    Approve button's third value segment.
    """
    from agents.schemas import ProjectPlan
    from app.config import settings
    from slack.blocks import render_approval_card

    monkeypatch.setattr(settings, "notion_api_key", "secret-token")

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, notion_enabled=True
    )
    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]

    checkbox = next(el for el in elements if el.get("action_id") == "select_notion_brief")
    assert checkbox["type"] == "checkboxes"
    assert len(checkbox["options"]) == 1
    assert [opt["value"] for opt in checkbox["initial_options"]] == [checkbox["options"][0]["value"]]

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-123|github|true"


def test_approval_card_omits_initial_options_when_notion_checkbox_unchecked(monkeypatch, valid_plan_dict):
    """T005 [US1] — Notion brief toggle, unchecked case: ``initial_options`` must be omitted
    entirely (an empty list is invalid per the Slack API), and the Approve value's third
    segment reflects the unchecked state."""
    from agents.schemas import ProjectPlan
    from app.config import settings
    from slack.blocks import render_approval_card

    monkeypatch.setattr(settings, "notion_api_key", "secret-token")

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, notion_enabled=False
    )
    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]

    checkbox = next(el for el in elements if el.get("action_id") == "select_notion_brief")
    assert "initial_options" not in checkbox

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-123|github|false"


def test_approval_card_omits_notion_checkbox_entirely_when_unconfigured(monkeypatch, valid_plan_dict):
    """T018 [US3] — toggle-hidden-when-unconfigured test (FR-201; contracts/block-kit.md).

    When settings.notion_api_key is unset, the Notion checkboxes block must be omitted
    entirely -- not shown-and-disabled -- so an unconfigured deployment's card looks exactly
    like v1/MVP2's. The Approve button's value still always carries its third segment
    (default "false"), so handle_approve never needs to branch on whether Notion was
    configured at render time.
    """
    from agents.schemas import ProjectPlan
    from app.config import settings
    from slack.blocks import render_approval_card

    monkeypatch.setattr(settings, "notion_api_key", None)

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(proposal_id="prop-123", plan=plan)
    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]

    assert not any(el.get("action_id") == "select_notion_brief" for el in elements)

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-123|github|false"


def test_approval_card_never_encodes_notion_true_when_unconfigured_even_if_enabled_arg_is_true(
    monkeypatch, valid_plan_dict
):
    """T022 [US3] — audit fix: a misconfigured deployment (DEFAULT_NOTION_ENABLED=true but no
    NOTION_API_KEY, which resolves to notion_enabled=True at call time) must not leak that True
    into the Approve value just because the checkbox itself is correctly hidden -- data-model.md's
    invariant is that execution "never even considers notion_enabled as anything but its hidden
    default (False)" when unconfigured, not just that the checkbox is hidden. Passing
    notion_enabled=True directly exercises the exact value the (import-time-bound) default would
    resolve to in that misconfiguration, without relying on monkeypatching a default that's
    already bound at function-definition time.
    """
    from agents.schemas import ProjectPlan
    from app.config import settings
    from slack.blocks import render_approval_card

    monkeypatch.setattr(settings, "notion_api_key", None)

    plan = ProjectPlan(**valid_plan_dict)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, notion_enabled=True
    )
    elements = [el for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]

    assert not any(el.get("action_id") == "select_notion_brief" for el in elements)

    approve = next(el for el in elements if el.get("action_id") == "approve_plan")
    assert approve["value"] == "prop-123|github|false"


@pytest.mark.parametrize(
    ("target_system", "expected"),
    [
        ("github", "*Proposed actions:* Create 2 GitHub issues"),
        ("jira", "*Proposed actions:* Create 2 Jira tickets"),
        ("both", "*Proposed actions:* Create 2 GitHub issues + 2 Jira tickets"),
    ],
)
def test_approval_card_proposed_actions_name_the_selected_target_system(
    valid_plan_dict, target_system, expected
):
    """FR-009 — the proposed external actions reflect the selected target system(s) instead of
    always saying "GitHub issue(s)"."""
    from agents.schemas import ProjectPlan
    from slack.blocks import render_approval_card

    task = valid_plan_dict["tasks"][0]
    valid_plan_dict["tasks"] = [task, {**task, "title": "Write copy"}]
    blocks = render_approval_card(
        proposal_id="prop-123",
        plan=ProjectPlan(**valid_plan_dict),
        target_system=target_system,
    )

    assert _proposed_actions_text(blocks) == expected


def test_approval_card_proposed_actions_list_notion_brief_only_when_configured(
    monkeypatch, valid_plan_dict
):
    """FR-009 + AC-203 — the Notion brief is listed when toggled on, and never when the
    notion_api_key guard forces notion_enabled off."""
    from agents.schemas import ProjectPlan
    from app.config import settings
    from slack.blocks import render_approval_card

    plan = ProjectPlan(**valid_plan_dict)

    monkeypatch.setattr(settings, "notion_api_key", "secret-token")
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, notion_enabled=True
    )
    assert _proposed_actions_text(blocks) == (
        "*Proposed actions:* Create 1 GitHub issue + 1 Notion project brief"
    )

    monkeypatch.setattr(settings, "notion_api_key", None)
    blocks = render_approval_card(
        proposal_id="prop-123", plan=plan, notion_enabled=True
    )
    assert "Notion" not in _proposed_actions_text(blocks)


async def _run_card_action(handler, blocks, action):
    responded: dict = {}

    async def ack():
        pass

    async def respond(**kwargs):
        responded.update(kwargs)

    await handler(
        ack=ack, body={"message": {"blocks": blocks}}, action=action, respond=respond
    )
    return responded["blocks"]


@pytest.mark.asyncio
async def test_select_target_system_rewrites_proposed_actions_text(valid_plan_dict):
    """FR-009 regression — switching the target in place must update the proposed-actions text
    along with the Approve value; it used to keep saying "GitHub issue(s)"."""
    from agents.schemas import ProjectPlan
    from slack.actions import handle_select_target_system
    from slack.blocks import render_approval_card

    blocks = render_approval_card(
        proposal_id="prop-123", plan=ProjectPlan(**valid_plan_dict)
    )
    blocks = await _run_card_action(
        handle_select_target_system, blocks, {"selected_option": {"value": "jira"}}
    )

    assert _proposed_actions_text(blocks) == "*Proposed actions:* Create 1 Jira ticket"


@pytest.mark.asyncio
async def test_select_notion_brief_rewrites_proposed_actions_text(
    monkeypatch, valid_plan_dict
):
    """FR-009 regression — ticking the Notion brief in place adds it to the proposed actions while
    keeping the already-selected target system(s)."""
    from agents.schemas import ProjectPlan
    from app.config import settings
    from slack.actions import handle_select_notion_brief
    from slack.blocks import render_approval_card

    monkeypatch.setattr(settings, "notion_api_key", "secret-token")
    blocks = render_approval_card(
        proposal_id="prop-123",
        plan=ProjectPlan(**valid_plan_dict),
        target_system="both",
        notion_enabled=False,
    )
    blocks = await _run_card_action(
        handle_select_notion_brief,
        blocks,
        {"selected_options": [{"value": "notion_brief"}]},
    )

    assert _proposed_actions_text(blocks) == (
        "*Proposed actions:* Create 1 GitHub issue + 1 Jira ticket + 1 Notion project brief"
    )


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


def test_stakeholder_summary_renders_notion_generated_line_for_succeeded_or_skipped_outcome():
    """T007 [US1] — Notion generated-brief summary line (FR-206; contracts/block-kit.md).

    RED until T013 adds notion_outcome to render_stakeholder_summary.
    """
    from db.models import ActionLogStatus
    from slack.blocks import render_stakeholder_summary
    from tools.github import IssueOutcome

    for status in (ActionLogStatus.SUCCEEDED, ActionLogStatus.SKIPPED_DUPLICATE):
        outcome = IssueOutcome(status, "page-1", "https://notion.so/page-1")
        blocks = render_stakeholder_summary(
            project_name="Onboarding Redesign",
            created_by_system={"github": [("Build wireframes", "https://github.com/x/y/issues/1")]},
            failed_by_system={"github": []},
            open_risks=[],
            next_steps="Track the created issues to completion.",
            notion_outcome=outcome,
        )
        text = json.dumps(blocks)
        assert "Notion" in text
        assert "1 project brief" in text
        assert "https://notion.so/page-1" in text


def test_stakeholder_summary_renders_notion_failed_line_explicitly():
    """T008 [US1] — Notion failed-brief summary line, never silently omitted (FR-206;
    spec.md Clarifications session 2026-07-12, SC-207).

    RED until T013 adds notion_outcome to render_stakeholder_summary.
    """
    from db.models import ActionLogStatus
    from slack.blocks import render_stakeholder_summary
    from tools.github import IssueOutcome

    outcome = IssueOutcome(ActionLogStatus.FAILED, None, None, "Notion 500")
    blocks = render_stakeholder_summary(
        project_name="Onboarding Redesign",
        created_by_system={"github": [("Build wireframes", "https://github.com/x/y/issues/1")]},
        failed_by_system={"github": []},
        open_risks=[],
        next_steps="Track the created issues to completion.",
        notion_outcome=outcome,
    )
    text = json.dumps(blocks)
    assert "Notion" in text
    assert "brief failed" in text
    assert "audit log" in text


def test_stakeholder_summary_renders_no_notion_line_when_outcome_is_none():
    """T021 [US3] — not-attempted summary-line test (SC-203; contracts/block-kit.md).

    notion_outcome defaults to None -- toggle off, unconfigured, or rejected -- and the summary
    must render byte-for-byte identical to v1/MVP2 output, with no Notion section at all.
    """
    from slack.blocks import render_stakeholder_summary

    kwargs = dict(
        project_name="Onboarding Redesign",
        created_by_system={"github": [("Build wireframes", "https://github.com/x/y/issues/1")]},
        failed_by_system={"github": []},
        open_risks=[],
        next_steps="Track the created issues to completion.",
    )
    blocks_without_param = render_stakeholder_summary(**kwargs)
    blocks_with_explicit_none = render_stakeholder_summary(**kwargs, notion_outcome=None)

    assert blocks_without_param == blocks_with_explicit_none
    assert "Notion" not in json.dumps(blocks_without_param)

