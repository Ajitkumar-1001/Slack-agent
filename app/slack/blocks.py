"""Reusable Slack Block Kit builders for FlowPilot AI."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.schemas import ProjectOut, ProjectPlan, ProjectSummaryResponse, RiskOut, TaskOut

ACTION_GENERATE_PLAN = "generate_plan"
ACTION_CREATE_TASKS = "create_tasks"
ACTION_SHOW_RISKS = "show_risks"
ACTION_WEEKLY_SUMMARY = "weekly_summary"


def _divider() -> dict[str, Any]:
    return {"type": "divider"}


def _header(text: str) -> dict[str, Any]:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _section_md(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def action_buttons(project_id: UUID | str) -> dict[str, Any]:
    pid = str(project_id)
    return {
        "type": "actions",
        "block_id": f"flowpilot_actions_{pid}",
        "elements": [
            {
                "type": "button",
                "action_id": ACTION_GENERATE_PLAN,
                "text": {"type": "plain_text", "text": "Generate Plan", "emoji": True},
                "style": "primary",
                "value": pid,
            },
            {
                "type": "button",
                "action_id": ACTION_CREATE_TASKS,
                "text": {"type": "plain_text", "text": "Create Tasks", "emoji": True},
                "value": pid,
            },
            {
                "type": "button",
                "action_id": ACTION_SHOW_RISKS,
                "text": {"type": "plain_text", "text": "Show Risks", "emoji": True},
                "value": pid,
            },
            {
                "type": "button",
                "action_id": ACTION_WEEKLY_SUMMARY,
                "text": {"type": "plain_text", "text": "Weekly Summary", "emoji": True},
                "value": pid,
            },
        ],
    }


def loading_blocks(goal: str) -> list[dict[str, Any]]:
    return [
        _header("FlowPilot AI"),
        _section_md(f":hourglass_flowing_sand: *Generating plan for:*\n>{goal}"),
        _context("_Analyzing milestones, tasks, and risks…_"),
    ]


def project_plan_blocks(plan: ProjectPlan, project_id: UUID | str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        _header(f":rocket: {plan.project_title}"),
        _section_md(
            f"*Objective*\n{plan.objective}\n\n"
            f"*Timeline*\n:calendar: {plan.timeline}"
        ),
        _divider(),
        *_milestone_blocks(plan),
        _divider(),
        action_buttons(project_id),
        _context(":flowpilot: FlowPilot AI • Project plan ready"),
    ]
    return blocks


def milestone_blocks_from_project(project: ProjectOut) -> list[dict[str, Any]]:
    if not project.milestones:
        return [_section_md("_No milestones yet._")]
    lines = []
    for i, m in enumerate(project.milestones, 1):
        due = f" — *{m.due_date}*" if m.due_date else ""
        desc = f"\n_{m.description}_" if m.description else ""
        lines.append(f"*{i}. {m.title}*{due}{desc}")
    return [_section_md("*Milestones*\n" + "\n".join(lines))]


def _milestone_blocks(plan: ProjectPlan) -> list[dict[str, Any]]:
    lines = []
    for i, m in enumerate(plan.milestones, 1):
        lines.append(f"*{i}. {m.title}* — _{m.due}_\n{m.description}")
    return [_section_md("*Milestones*\n" + "\n\n".join(lines))]


def task_blocks(tasks: list[TaskOut] | list[Any], *, title: str = "Tasks") -> list[dict[str, Any]]:
    if not tasks:
        return [_section_md(f"*{title}*\n_No tasks yet._")]

    rows: list[dict[str, Any]] = []
    for t in tasks:
        owner = getattr(t, "owner_role", None) or "Unassigned"
        priority = getattr(t, "priority", "medium")
        emoji = {"high": ":red_circle:", "medium": ":large_yellow_circle:", "low": ":large_green_circle:"}.get(
            priority.lower(), ":white_circle:"
        )
        task_title = getattr(t, "title", str(t))
        desc = getattr(t, "description", "") or ""
        rows.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{emoji} *{task_title}*\n{desc}"},
                "fields": [
                    {"type": "mrkdwn", "text": f"*Owner*\n{owner}"},
                    {"type": "mrkdwn", "text": f"*Priority*\n{priority.title()}"},
                ],
            }
        )
    return [_header(f":clipboard: {title}"), *rows]


def risk_blocks(risks: list[RiskOut] | list[Any]) -> list[dict[str, Any]]:
    if not risks:
        return [_section_md(":white_check_mark: *No open risks identified.*")]

    blocks: list[dict[str, Any]] = [_header(":warning: Project Risks")]
    for r in risks:
        severity = getattr(r, "severity", "medium")
        risk_text = getattr(r, "risk", str(r))
        mitigation = getattr(r, "mitigation", "") or ""
        sev_emoji = {"high": ":rotating_light:", "medium": ":warning:", "low": ":information_source:"}.get(
            severity.lower(), ":warning:"
        )
        blocks.append(
            _section_md(
                f"{sev_emoji} *{risk_text}*\n"
                f"*Severity:* {severity.title()}\n"
                f"*Mitigation:* {mitigation}"
            )
        )
    return blocks


def weekly_summary_blocks(summary: ProjectSummaryResponse, project_id: UUID | str) -> list[dict[str, Any]]:
    progress_emoji = ":large_green_circle:" if summary.open_risk_count == 0 else ":large_yellow_circle:"
    content = summary.latest_summary or "_No summary available yet._"
    return [
        _header(":bar_chart: Weekly Summary"),
        _section_md(
            f"*Project:* {summary.project_title or 'Untitled'}\n"
            f"*Status:* {summary.status.title()}\n"
            f"*Timeline:* {summary.timeline or 'TBD'}\n"
            f"*Tasks:* {summary.task_count}\n"
            f"*Open risks:* {summary.open_risk_count} {progress_emoji}"
        ),
        _divider(),
        _section_md(content),
        _divider(),
        action_buttons(project_id),
        _context(f"Generated {summary.generated_at.strftime('%b %d, %Y %H:%M UTC')}"),
    ]


def full_project_blocks(project: ProjectOut) -> list[dict[str, Any]]:
    """Complete project view combining plan, milestones, tasks, and actions."""
    blocks: list[dict[str, Any]] = [
        _header(f":rocket: {project.project_title or project.goal}"),
        _section_md(
            f"*Objective*\n{project.objective or '—'}\n\n"
            f"*Timeline*\n:calendar: {project.timeline or '—'}"
        ),
        _divider(),
        *milestone_blocks_from_project(project),
    ]
    if project.tasks:
        blocks.append(_divider())
        blocks.extend(task_blocks(project.tasks))
    if project.risks:
        blocks.append(_divider())
        blocks.extend(risk_blocks(project.risks))
    blocks.extend(
        [
            _divider(),
            action_buttons(project.id),
            _context(":flowpilot: FlowPilot AI"),
        ]
    )
    return blocks


def error_blocks(message: str) -> list[dict[str, Any]]:
    return [
        _header(":x: FlowPilot Error"),
        _section_md(message),
        _context("Try `/flowpilot <your project goal>` again or contact your admin."),
    ]
