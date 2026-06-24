"""REST API routes for projects."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectSummaryResponse,
    RiskOut,
    TaskOut,
)
from app.services.project_service import get_project_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(payload: ProjectCreate) -> ProjectOut:
    service = get_project_service()
    try:
        return await service.create_project(payload)
    except Exception as exc:
        logger.exception("Failed to create project")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: UUID) -> ProjectOut:
    service = get_project_service()
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/tasks", response_model=list[TaskOut])
async def get_project_tasks(project_id: UUID) -> list[TaskOut]:
    service = get_project_service()
    if not service.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return service.get_tasks(project_id)


@router.get("/{project_id}/risks", response_model=list[RiskOut])
async def get_project_risks(project_id: UUID) -> list[RiskOut]:
    service = get_project_service()
    if not service.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return service.get_risks(project_id)


@router.get("/{project_id}/summary", response_model=ProjectSummaryResponse)
async def get_project_summary(project_id: UUID) -> ProjectSummaryResponse:
    service = get_project_service()
    summary = service.get_summary(project_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Project not found")
    return summary
