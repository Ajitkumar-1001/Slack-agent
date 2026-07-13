"""Block Kit renderers (contracts/block-kit.md). Pure functions — no DB/business logic."""

from collections.abc import Mapping, Sequence

from agents.schemas import ProjectPlan
from app.config import settings
from db.models import ActionLogStatus
from tools.github import IssueOutcome

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_TARGET_SYSTEM_OPTIONS = [
    {"text": {"type": "plain_text", "text": "GitHub"}, "value": "github"},
    {"text": {"type": "plain_text", "text": "Jira"}, "value": "jira"},
    {"text": {"type": "plain_text", "text": "Both"}, "value": "both"},
]


_NOTION_CHECKBOX_OPTION = {
    "text": {"type": "plain_text", "text": "Generate Notion project brief"},
    "value": "notion_brief",
}


def render_approval_card(
    *,
    proposal_id: str,
    plan: ProjectPlan,
    action_summary: str,
    target_system: str = settings.default_target_system,
    notion_enabled: bool = settings.default_notion_enabled,
) -> list[dict]:
    """Summarize (not dump) the plan as a Block Kit approval message with a target-system
    selector (FR-101) and Approve / Edit / Reject buttons. Approve's value carries the
    currently-selected target system and Notion-brief toggle (research.md Decision 1);
    Edit/Reject just carry proposal_id, since neither creates an external artifact.

    The Notion checkbox (FR-201) is omitted entirely when settings.notion_api_key is unset —
    not shown-and-disabled — so an unconfigured deployment's card looks exactly like v1/MVP2's."""
    top_risks = sorted(plan.risks, key=lambda r: _SEVERITY_ORDER[r.severity])[:3]
    risk_lines = "\n".join(
        f"• *{r.title}* ({r.severity}) — {r.mitigation}" for r in top_risks
    )
    # T022 audit: force notion_enabled off whenever notion_api_key is unset, so a misconfigured
    # deployment (e.g. DEFAULT_NOTION_ENABLED=true with no NOTION_API_KEY) can never bake "true"
    # into the Approve value just because the checkbox itself is correctly hidden (AC-203).
    notion_enabled = notion_enabled and bool(settings.notion_api_key)
    notion_flag = "true" if notion_enabled else "false"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": plan.project_name}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Objective:* {plan.objective}\n"
                    f"*Timeline:* {plan.timeline or 'not specified'}"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Milestones:* {len(plan.milestones)}   "
                    f"*Tasks:* {len(plan.tasks)}   "
                    f"*Risks:* {len(plan.risks)}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top risks:*\n{risk_lines}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Proposed actions:* {action_summary}"},
        },
        {
            "type": "actions",
            "block_id": "target_system_select",
            "elements": [
                {
                    "type": "static_select",
                    "action_id": "select_target_system",
                    "options": _TARGET_SYSTEM_OPTIONS,
                    "initial_option": next(
                        opt for opt in _TARGET_SYSTEM_OPTIONS if opt["value"] == target_system
                    ),
                },
            ],
        },
    ]

    if settings.notion_api_key:
        checkbox: dict = {
            "type": "checkboxes",
            "action_id": "select_notion_brief",
            "options": [_NOTION_CHECKBOX_OPTION],
        }
        if notion_enabled:
            checkbox["initial_options"] = [_NOTION_CHECKBOX_OPTION]
        blocks.append({"type": "actions", "block_id": "notion_brief_select", "elements": [checkbox]})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "approve_plan",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": f"{proposal_id}|{target_system}|{notion_flag}",
                },
                {
                    "type": "button",
                    "action_id": "edit_plan",
                    "text": {"type": "plain_text", "text": "Edit Plan"},
                    "value": proposal_id,
                },
                {
                    "type": "button",
                    "action_id": "reject_plan",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "value": proposal_id,
                },
            ],
        }
    )
    return blocks


def render_already_decided_notice(*, status: str) -> str:
    """FR-021: ephemeral text shown to a user who clicks Approve/Edit/Reject on a proposal that is
    already decided or executing. Plain text — delivered ephemerally to the clicker, not to the channel."""
    return (
        f"This plan is already *{status.removeprefix('proposal_')}* — the first decision wins, "
        "so no further action was taken."
    )


_SYSTEM_ORDER = ("github", "jira")
_SYSTEM_LABELS = {"github": ("GitHub", "issue"), "jira": ("Jira", "ticket")}


def render_stakeholder_summary(
    *,
    project_name: str,
    created_by_system: Mapping[str, Sequence[tuple[str, str]]],
    failed_by_system: Mapping[str, Sequence[str]],
    open_risks: Sequence[str],
    next_steps: str,
    notion_outcome: IssueOutcome | None = None,
) -> list[dict]:
    """Post-execution summary (FR-016/FR-017/FR-105): one Created section per system with any
    artifacts, a per-system succeeded/failed breakdown when any system has failures, open risks,
    and next steps. A single-target run degenerates to one system's section (v1-equivalent)."""
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{project_name} — execution summary"}},
    ]
    systems = [s for s in _SYSTEM_ORDER if created_by_system.get(s) or failed_by_system.get(s)]

    for system in systems:
        items = created_by_system.get(system) or []
        if not items:
            continue
        label, noun = _SYSTEM_LABELS[system]
        lines = "\n".join(f"• <{url}|{title}>" for title, url in items)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{label}:* {len(items)} {noun}{'s' if len(items) != 1 else ''}\n{lines}",
                },
            }
        )

    if any(failed_by_system.values()):
        for system in systems:
            label, _noun = _SYSTEM_LABELS[system]
            succeeded = len(created_by_system.get(system) or [])
            failed = failed_by_system.get(system) or []
            text = f"*{label}:* {succeeded} succeeded"
            if failed:
                failed_lines = "\n".join(f"• {title}" for title in failed)
                text += f", {len(failed)} failed\n{failed_lines}"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    if notion_outcome is not None:
        if notion_outcome.status in (ActionLogStatus.SUCCEEDED, ActionLogStatus.SKIPPED_DUPLICATE):
            text = f"*Notion:* 1 project brief (<{notion_outcome.external_url}|link>)"
        else:  # FAILED — always explicit, never silently omitted (spec.md Clarifications 2026-07-12)
            text = "*Notion:* brief failed (see audit log)"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    if open_risks:
        risk_lines = "\n".join(f"• {risk}" for risk in open_risks)
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Open risks:*\n{risk_lines}"}}
        )
    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Next steps:* {next_steps}"}}
    )
    return blocks
