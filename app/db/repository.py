"""Supabase database client and repository layer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from supabase import Client, create_client

from app.config import get_settings
from app.models.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectPlan,
    ProjectSummaryResponse,
    RiskOut,
    SummaryOut,
    TaskOut,
)

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_supabase() -> Client | None:
    global _client
    settings = get_settings()
    if not settings.db_configured:
        return None
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


class ProjectRepository:
    """CRUD operations backed by Supabase tables."""

    def __init__(self) -> None:
        self._memory: dict[str, Any] = {"projects": {}, "tasks": {}, "risks": {}, "summaries": {}, "milestones": {}}

    def _use_db(self) -> bool:
        return get_supabase() is not None

    def create_project_from_plan(
        self,
        goal: str,
        plan: ProjectPlan,
        *,
        slack_team_id: str | None = None,
        slack_channel_id: str | None = None,
        slack_user_id: str | None = None,
    ) -> ProjectOut:
        if self._use_db():
            return self._db_create_project(goal, plan, slack_team_id, slack_channel_id, slack_user_id)
        return self._memory_create_project(goal, plan, slack_team_id, slack_channel_id, slack_user_id)

    def get_project(self, project_id: UUID) -> ProjectOut | None:
        if self._use_db():
            return self._db_get_project(project_id)
        return self._memory_get_project(project_id)

    def get_tasks(self, project_id: UUID) -> list[TaskOut]:
        project = self.get_project(project_id)
        return project.tasks if project else []

    def get_risks(self, project_id: UUID) -> list[RiskOut]:
        project = self.get_project(project_id)
        return project.risks if project else []

    def get_summary(self, project_id: UUID) -> ProjectSummaryResponse | None:
        project = self.get_project(project_id)
        if not project:
            return None
        latest = project.summaries[0].content if project.summaries else plan_summary_fallback(project)
        open_risks = sum(1 for r in project.risks if r.status == "open")
        return ProjectSummaryResponse(
            project_id=project.id,
            project_title=project.project_title,
            timeline=project.timeline,
            status=project.status,
            task_count=len(project.tasks),
            open_risk_count=open_risks,
            latest_summary=latest,
            generated_at=datetime.now(timezone.utc),
        )

    def log_slack_message(self, record: dict[str, Any]) -> None:
        if not self._use_db():
            return
        client = get_supabase()
        assert client is not None
        try:
            client.table("slack_messages").insert(record).execute()
        except Exception:
            logger.exception("Failed to log slack message")

    # -- Supabase implementations ------------------------------------------------

    def _db_create_project(
        self,
        goal: str,
        plan: ProjectPlan,
        slack_team_id: str | None,
        slack_channel_id: str | None,
        slack_user_id: str | None,
    ) -> ProjectOut:
        client = get_supabase()
        assert client is not None

        project_row = {
            "goal": goal,
            "project_title": plan.project_title,
            "objective": plan.objective,
            "timeline": plan.timeline,
            "status": "active",
            "slack_team_id": slack_team_id,
            "slack_channel_id": slack_channel_id,
            "slack_user_id": slack_user_id,
        }
        result = client.table("projects").insert(project_row).execute()
        project_id = UUID(result.data[0]["id"])

        for m in plan.milestones:
            client.table("milestones").insert(
                {
                    "project_id": str(project_id),
                    "title": m.title,
                    "description": m.description,
                    "due_date": m.due,
                }
            ).execute()

        for t in plan.tasks:
            client.table("tasks").insert(
                {
                    "project_id": str(project_id),
                    "title": t.title,
                    "owner_role": t.owner_role,
                    "priority": t.priority,
                    "description": t.description,
                }
            ).execute()

        for r in plan.risks:
            client.table("risks").insert(
                {
                    "project_id": str(project_id),
                    "risk": r.risk,
                    "severity": r.severity,
                    "mitigation": r.mitigation,
                }
            ).execute()

        client.table("summaries").insert(
            {
                "project_id": str(project_id),
                "summary_type": "initial",
                "content": plan.summary,
            }
        ).execute()

        project = self._db_get_project(project_id)
        assert project is not None
        return project

    def _db_get_project(self, project_id: UUID) -> ProjectOut | None:
        client = get_supabase()
        assert client is not None

        proj = client.table("projects").select("*").eq("id", str(project_id)).maybe_single().execute()
        if not proj.data:
            return None

        milestones = (
            client.table("milestones").select("*").eq("project_id", str(project_id)).execute().data or []
        )
        tasks = client.table("tasks").select("*").eq("project_id", str(project_id)).execute().data or []
        risks = client.table("risks").select("*").eq("project_id", str(project_id)).execute().data or []
        summaries = (
            client.table("summaries")
            .select("*")
            .eq("project_id", str(project_id))
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )

        return ProjectOut(
            **proj.data,
            milestones=milestones,
            tasks=tasks,
            risks=risks,
            summaries=summaries,
        )

    # -- In-memory fallback (local dev without Supabase) -------------------------

    def _memory_create_project(
        self,
        goal: str,
        plan: ProjectPlan,
        slack_team_id: str | None,
        slack_channel_id: str | None,
        slack_user_id: str | None,
    ) -> ProjectOut:
        import uuid

        now = datetime.now(timezone.utc)
        project_id = uuid.uuid4()
        pid = str(project_id)

        project_data = {
            "id": project_id,
            "goal": goal,
            "project_title": plan.project_title,
            "objective": plan.objective,
            "timeline": plan.timeline,
            "status": "active",
            "slack_team_id": slack_team_id,
            "slack_channel_id": slack_channel_id,
            "slack_user_id": slack_user_id,
            "created_at": now,
            "updated_at": now,
        }
        self._memory["projects"][pid] = project_data

        milestones, tasks, risks, summaries = [], [], [], []
        for m in plan.milestones:
            row = {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "title": m.title,
                "description": m.description,
                "due_date": m.due,
                "status": "pending",
                "created_at": now,
            }
            milestones.append(row)
        for t in plan.tasks:
            row = {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "title": t.title,
                "owner_role": t.owner_role,
                "priority": t.priority,
                "description": t.description,
                "status": "todo",
                "created_at": now,
            }
            tasks.append(row)
        for r in plan.risks:
            row = {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "risk": r.risk,
                "severity": r.severity,
                "mitigation": r.mitigation,
                "status": "open",
                "created_at": now,
            }
            risks.append(row)
        summaries.append(
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "summary_type": "initial",
                "content": plan.summary,
                "created_at": now,
            }
        )

        self._memory["milestones"][pid] = milestones
        self._memory["tasks"][pid] = tasks
        self._memory["risks"][pid] = risks
        self._memory["summaries"][pid] = summaries

        return ProjectOut(**project_data, milestones=milestones, tasks=tasks, risks=risks, summaries=summaries)

    def _memory_get_project(self, project_id: UUID) -> ProjectOut | None:
        pid = str(project_id)
        project = self._memory["projects"].get(pid)
        if not project:
            return None
        return ProjectOut(
            **project,
            milestones=self._memory["milestones"].get(pid, []),
            tasks=self._memory["tasks"].get(pid, []),
            risks=self._memory["risks"].get(pid, []),
            summaries=self._memory["summaries"].get(pid, []),
        )


def plan_summary_fallback(project: ProjectOut) -> str:
    return (
        f"Project **{project.project_title or project.goal}** — "
        f"{len(project.tasks)} tasks, {len(project.risks)} risks tracked."
    )


def get_repository() -> ProjectRepository:
    return ProjectRepository()
