"""Pydantic schemas for API and agent contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent contract (integration surface for AI team)
# ---------------------------------------------------------------------------


class MilestonePlan(BaseModel):
    title: str
    description: str
    due: str


class TaskPlan(BaseModel):
    title: str
    owner_role: str
    priority: str
    description: str


class RiskPlan(BaseModel):
    risk: str
    severity: str
    mitigation: str


class ProjectPlan(BaseModel):
    project_title: str
    objective: str
    timeline: str
    milestones: list[MilestonePlan]
    tasks: list[TaskPlan]
    risks: list[RiskPlan]
    summary: str


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    goal: str = Field(..., min_length=3, max_length=2000)
    slack_team_id: str | None = None
    slack_channel_id: str | None = None
    slack_user_id: str | None = None


class MilestoneOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str | None = None
    due_date: str | None = None
    status: str
    created_at: datetime


class TaskOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    owner_role: str | None = None
    priority: str
    description: str | None = None
    status: str
    created_at: datetime


class RiskOut(BaseModel):
    id: UUID
    project_id: UUID
    risk: str
    severity: str
    mitigation: str | None = None
    status: str
    created_at: datetime


class SummaryOut(BaseModel):
    id: UUID
    project_id: UUID
    summary_type: str
    content: str
    created_at: datetime


class ProjectOut(BaseModel):
    id: UUID
    goal: str
    project_title: str | None = None
    objective: str | None = None
    timeline: str | None = None
    status: str
    slack_team_id: str | None = None
    slack_channel_id: str | None = None
    slack_user_id: str | None = None
    created_at: datetime
    updated_at: datetime
    milestones: list[MilestoneOut] = Field(default_factory=list)
    tasks: list[TaskOut] = Field(default_factory=list)
    risks: list[RiskOut] = Field(default_factory=list)
    summaries: list[SummaryOut] = Field(default_factory=list)


class ProjectSummaryResponse(BaseModel):
    project_id: UUID
    project_title: str | None
    timeline: str | None
    status: str
    task_count: int
    open_risk_count: int
    latest_summary: str | None = None
    generated_at: datetime


class HealthResponse(BaseModel):
    status: str
    version: str
    slack_configured: bool
    db_configured: bool


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class SlackMessageRecord(BaseModel):
    project_id: UUID | None = None
    slack_team_id: str | None = None
    slack_channel_id: str | None = None
    slack_user_id: str | None = None
    message_ts: str | None = None
    message_type: str
    payload: dict[str, Any] | None = None
