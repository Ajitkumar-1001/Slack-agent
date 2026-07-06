from fastapi import APIRouter, Request
from fastapi.responses import Response
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

import slack.actions  # noqa: F401  (registers the Bolt action handlers on bolt_app)
import slack.events  # noqa: F401  (registers the Bolt event handlers on bolt_app)
from slack.app import bolt_app

handler = AsyncSlackRequestHandler(bolt_app)
router = APIRouter()


@router.post("/slack/events")
async def slack_events(req: Request) -> Response:
    return await handler.handle(req)


@router.post("/slack/actions")
async def slack_actions(req: Request) -> Response:
    return await handler.handle(req)
