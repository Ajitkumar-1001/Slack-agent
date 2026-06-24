"""Business logic for project creation and Slack workflows."""

from __future__ import annotations

import logging
from uuid import UUID

from app.agents.orchestrator import generate_project_plan_async
from app.db.repository import get_repository
from app.models.schemas import ProjectCreate, ProjectOut, ProjectSummaryResponse
from app.slack import blocks as slack_blocks

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self) -> None:
        self.repo = get_repository()

    async def create_project(self, payload: ProjectCreate) -> ProjectOut:
        logger.info("Creating project for goal: %s", payload.goal[:80])
        plan = await generate_project_plan_async(payload.goal)
        project = self.repo.create_project_from_plan(
            payload.goal,
            plan,
            slack_team_id=payload.slack_team_id,
            slack_channel_id=payload.slack_channel_id,
            slack_user_id=payload.slack_user_id,
        )
        return project

    def get_project(self, project_id: UUID) -> ProjectOut | None:
        return self.repo.get_project(project_id)

    def get_tasks(self, project_id: UUID):
        return self.repo.get_tasks(project_id)

    def get_risks(self, project_id: UUID):
        return self.repo.get_risks(project_id)

    def get_summary(self, project_id: UUID) -> ProjectSummaryResponse | None:
        return self.repo.get_summary(project_id)

    async def build_slack_plan_blocks(self, goal: str, project: ProjectOut | None = None):
        if project:
            return slack_blocks.full_project_blocks(project)
        plan = await generate_project_plan_async(goal)
        pid = project.id if project else "preview"
        return slack_blocks.project_plan_blocks(plan, pid)

    def blocks_for_action(self, action: str, project_id: UUID) -> list:
        project = self.repo.get_project(project_id)
        if not project:
            return slack_blocks.error_blocks(f"Project `{project_id}` not found.")

        if action == slack_blocks.ACTION_GENERATE_PLAN:
            return slack_blocks.full_project_blocks(project)
        if action == slack_blocks.ACTION_CREATE_TASKS:
            return [
                *slack_blocks.task_blocks(project.tasks),
                {"type": "divider"},
                slack_blocks.action_buttons(project_id),
            ]
        if action == slack_blocks.ACTION_SHOW_RISKS:
            return [
                *slack_blocks.risk_blocks(project.risks),
                {"type": "divider"},
                slack_blocks.action_buttons(project_id),
            ]
        if action == slack_blocks.ACTION_WEEKLY_SUMMARY:
            summary = self.repo.get_summary(project_id)
            if not summary:
                return slack_blocks.error_blocks("Could not generate summary.")
            return slack_blocks.weekly_summary_blocks(summary, project_id)

        return slack_blocks.error_blocks(f"Unknown action: {action}")


def get_project_service() -> ProjectService:
    return ProjectService()
