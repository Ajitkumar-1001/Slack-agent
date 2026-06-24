"""Slack slash command, event, and interaction handlers."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.services.project_service import get_project_service
from app.slack import blocks as slack_blocks
from app.slack.client import post_response_url, respond_to_interaction
from app.slack.verify import verify_slack_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["slack"])


async def _process_flowpilot_command(
    *,
    goal: str,
    response_url: str,
    team_id: str,
    channel_id: str,
    user_id: str,
) -> None:
    service = get_project_service()
    try:
        from app.models.schemas import ProjectCreate

        project = await service.create_project(
            ProjectCreate(
                goal=goal,
                slack_team_id=team_id,
                slack_channel_id=channel_id,
                slack_user_id=user_id,
            )
        )
        blocks = slack_blocks.full_project_blocks(project)
        await post_response_url(response_url, blocks=blocks, text=f"Plan ready: {project.project_title}")
    except Exception:
        logger.exception("Failed to process /flowpilot command")
        await post_response_url(
            response_url,
            blocks=slack_blocks.error_blocks("Something went wrong generating your plan. Please try again."),
            text="FlowPilot error",
        )


@router.post("/commands")
async def slack_commands(request: Request, background_tasks: BackgroundTasks):
    body = await verify_slack_request(request)
    form = parse_qs(body.decode("utf-8"))

    command = form.get("command", [""])[0]
    text = form.get("text", [""])[0].strip()
    response_url = form.get("response_url", [""])[0]
    team_id = form.get("team_id", [""])[0]
    channel_id = form.get("channel_id", [""])[0]
    user_id = form.get("user_id", [""])[0]

    logger.info("Slash command received: %s %s", command, text[:60] if text else "")

    if command != "/flowpilot":
        return {"response_type": "ephemeral", "text": f"Unknown command: {command}"}

    if not text:
        return {
            "response_type": "ephemeral",
            "text": "Usage: `/flowpilot Launch customer onboarding redesign in 4 weeks`",
        }

    background_tasks.add_task(
        _process_flowpilot_command,
        goal=text,
        response_url=response_url,
        team_id=team_id,
        channel_id=channel_id,
        user_id=user_id,
    )

    return {
        "response_type": "in_channel",
        "blocks": slack_blocks.loading_blocks(text),
        "text": f"FlowPilot is planning: {text}",
    }


@router.post("/events")
async def slack_events(request: Request):
    body = await verify_slack_request(request)
    payload = json.loads(body.decode("utf-8"))

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    if payload.get("type") == "event_callback":
        event = payload.get("event", {})
        logger.info("Slack event: %s", event.get("type"))
        # Extend here for app_mention, message, etc.

    return {"ok": True}


@router.post("/interactions")
async def slack_interactions(request: Request, background_tasks: BackgroundTasks):
    body = await verify_slack_request(request)
    form = parse_qs(body.decode("utf-8"))
    payload_raw = form.get("payload", [""])[0]

    if not payload_raw:
        raise HTTPException(status_code=400, detail="Missing interaction payload")

    payload = json.loads(payload_raw)
    actions = payload.get("actions", [])
    if not actions:
        return {"ok": True}

    action = actions[0]
    action_id = action.get("action_id")
    project_id_str = action.get("value", "")
    response_url = payload.get("response_url", "")

    logger.info("Interaction: %s project=%s", action_id, project_id_str)

    try:
        project_id = UUID(project_id_str)
    except ValueError:
        return {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": "Invalid project reference.",
        }

    service = get_project_service()
    blocks = service.blocks_for_action(action_id, project_id)

    # Acknowledge immediately; post follow-up via response_url for slower paths
    background_tasks.add_task(
        respond_to_interaction,
        response_url,
        blocks=blocks,
        text="FlowPilot update",
    )

    return {"ok": True}
