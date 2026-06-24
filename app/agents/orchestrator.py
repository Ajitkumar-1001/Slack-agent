"""AI agent orchestration — integration contract for the planning service."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.models.schemas import ProjectPlan

logger = logging.getLogger(__name__)


def _mock_project_plan(project_goal: str) -> dict[str, Any]:
    """Deterministic demo plan for hackathon demos without an LLM."""
    title = project_goal.strip().rstrip(".")
    if len(title) > 60:
        title = title[:57] + "..."

    return {
        "project_title": title,
        "objective": f"Deliver on: {project_goal.strip()}",
        "timeline": "4 weeks",
        "milestones": [
            {
                "title": "Discovery & alignment",
                "description": "Stakeholder interviews, success metrics, scope lock.",
                "due": "Week 1",
            },
            {
                "title": "Design & prototype",
                "description": "UX flows, copy, and clickable prototype for review.",
                "due": "Week 2",
            },
            {
                "title": "Build & integrate",
                "description": "Implementation, QA, and integration with existing systems.",
                "due": "Week 3",
            },
            {
                "title": "Launch & measure",
                "description": "Rollout, monitoring, and post-launch retrospective.",
                "due": "Week 4",
            },
        ],
        "tasks": [
            {
                "title": "Define success metrics",
                "owner_role": "Product Manager",
                "priority": "high",
                "description": "Activation rate, time-to-value, support ticket volume.",
            },
            {
                "title": "Audit current onboarding flow",
                "owner_role": "UX Designer",
                "priority": "high",
                "description": "Map friction points and drop-off steps.",
            },
            {
                "title": "Draft implementation plan",
                "owner_role": "Engineering Lead",
                "priority": "medium",
                "description": "Break work into epics and estimate capacity.",
            },
            {
                "title": "Prepare launch comms",
                "owner_role": "Marketing",
                "priority": "medium",
                "description": "Internal announcement and customer-facing changelog.",
            },
        ],
        "risks": [
            {
                "risk": "Scope creep from late stakeholder requests",
                "severity": "high",
                "mitigation": "Lock scope after Week 1; use change-control for additions.",
            },
            {
                "risk": "Engineering capacity constrained by parallel initiatives",
                "severity": "medium",
                "mitigation": "Pre-allocate sprint capacity and identify a backup engineer.",
            },
            {
                "risk": "Insufficient analytics instrumentation",
                "severity": "medium",
                "mitigation": "Add tracking events in Week 2 before build freeze.",
            },
        ],
        "summary": (
            f"FlowPilot generated a 4-week execution plan for **{title}**. "
            "4 milestones, 4 tasks, and 3 risks identified. "
            "Next step: confirm owners and kick off discovery."
        ),
    }


async def _llm_project_plan(project_goal: str) -> dict[str, Any]:
    """Optional OpenAI-backed planner. Falls back to mock on failure."""
    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set; using mock plan")
        return _mock_project_plan(project_goal)

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a project planning agent. Return JSON matching this schema: "
                        '{"project_title": str, "objective": str, "timeline": str, '
                        '"milestones": [{"title": str, "description": str, "due": str}], '
                        '"tasks": [{"title": str, "owner_role": str, "priority": str, "description": str}], '
                        '"risks": [{"risk": str, "severity": str, "mitigation": str}], '
                        '"summary": str}'
                    ),
                },
                {"role": "user", "content": f"Create a project plan for: {project_goal}"},
            ],
        )
        import json

        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception:
        logger.exception("LLM plan generation failed; falling back to mock")
        return _mock_project_plan(project_goal)


def generate_project_plan(project_goal: str) -> dict[str, Any]:
    """
    Synchronous entry point for the AI agent service.

    The AI team can replace the body of this function with their orchestrator.
    Returns a dict matching the ProjectPlan schema.
    """
    settings = get_settings()
    if settings.agent_use_mock:
        return _mock_project_plan(project_goal)
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Called from async context — use mock to avoid nested loop issues
            return _mock_project_plan(project_goal)
        return loop.run_until_complete(_llm_project_plan(project_goal))
    except RuntimeError:
        return asyncio.run(_llm_project_plan(project_goal))


async def generate_project_plan_async(project_goal: str) -> ProjectPlan:
    """Async wrapper used by FastAPI handlers."""
    settings = get_settings()
    if settings.agent_use_mock:
        raw = _mock_project_plan(project_goal)
    else:
        raw = await _llm_project_plan(project_goal)
    return ProjectPlan.model_validate(raw)
