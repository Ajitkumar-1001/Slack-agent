"""Block Kit renderers (contracts/block-kit.md). Pure functions — no DB/business logic."""

from collections.abc import Sequence

from agents.schemas import ProjectPlan

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def render_approval_card(
    *, proposal_id: str, plan: ProjectPlan, action_summary: str
) -> list[dict]:
    """Summarize (not dump) the plan as a Block Kit approval message with Approve / Edit /
    Reject buttons, each carrying the proposal_id so the stateless action can rehydrate state."""
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
            "elements": [
                {
                    "type": "button",
                    "action_id": "approve_plan",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": proposal_id,
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


def render_stakeholder_summary(
    *,
    project_name: str,
    created: Sequence[tuple[str, str]],
    failed: Sequence[str],
    open_risks: Sequence[str],
    next_steps: str,
) -> list[dict]:
    """Post-execution summary (FR-016/FR-017): created issues with links, failed tasks, open
    risks, and next steps. `created` is (title, url) pairs; `failed` is task titles."""
    created_lines = "\n".join(f"• <{url}|{title}>" for title, url in created) or "_none_"
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{project_name} — execution summary"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Created issues:*\n{created_lines}"}},
    ]
    if failed:
        failed_lines = "\n".join(f"• {title}" for title in failed)
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Failed tasks:*\n{failed_lines}"}}
        )
    if open_risks:
        risk_lines = "\n".join(f"• {risk}" for risk in open_risks)
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Open risks:*\n{risk_lines}"}}
        )
    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Next steps:* {next_steps}"}}
    )
    return blocks
