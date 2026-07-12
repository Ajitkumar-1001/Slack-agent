"""Block Kit renderers (contracts/block-kit.md). Pure functions — no DB/business logic."""

from collections.abc import Mapping, Sequence

from agents.schemas import ProjectPlan
from app.config import settings

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_TARGET_SYSTEM_OPTIONS = [
    {"text": {"type": "plain_text", "text": "GitHub"}, "value": "github"},
    {"text": {"type": "plain_text", "text": "Jira"}, "value": "jira"},
    {"text": {"type": "plain_text", "text": "Both"}, "value": "both"},
]


def render_approval_card(
    *,
    proposal_id: str,
    plan: ProjectPlan,
    action_summary: str,
    target_system: str = settings.default_target_system,
) -> list[dict]:
    """Summarize (not dump) the plan as a Block Kit approval message with a target-system
    selector (FR-101) and Approve / Edit / Reject buttons. Approve's value carries the
    currently-selected target system (research.md Decision 1); Edit/Reject just carry
    proposal_id, since neither creates an external artifact."""
    top_risks = sorted(plan.risks, key=lambda r: _SEVERITY_ORDER[r.severity])[:3]
    risk_lines = "\n".join(
        f"• *{r.title}* ({r.severity}) — {r.mitigation}" for r in top_risks
    )

    return [
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
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "approve_plan",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": f"{proposal_id}|{target_system}",
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
        },
    ]


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

    if open_risks:
        risk_lines = "\n".join(f"• {risk}" for risk in open_risks)
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Open risks:*\n{risk_lines}"}}
        )
    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Next steps:* {next_steps}"}}
    )
    return blocks
