from typing import Literal

from pydantic import BaseModel


class Milestone(BaseModel):
    title: str
    description: str
    due_date: str | None
    success_criteria: list[str]


class Task(BaseModel):
    title: str
    description: str
    milestone: str | None
    suggested_owner: str | None
    priority: Literal["low", "medium", "high"]
    acceptance_criteria: list[str]
    dependencies: list[str]


class Risk(BaseModel):
    title: str
    severity: Literal["low", "medium", "high", "critical"]
    explanation: str
    mitigation: str


class Dependency(BaseModel):
    title: str
    description: str
    type: Literal["internal", "external", "decision"]
    blocking: bool


class ProjectPlan(BaseModel):
    project_name: str
    objective: str
    timeline: str | None
    milestones: list[Milestone]
    tasks: list[Task]
    risks: list[Risk]
    dependencies: list[Dependency]
    assumptions: list[str]
    evidence_summary: list[str]
