"""Slack Web API client helpers."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


async def post_message(
    *,
    channel: str,
    blocks: list[dict[str, Any]] | None = None,
    text: str = "FlowPilot update",
    thread_ts: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.slack_bot_token:
        logger.warning("SLACK_BOT_TOKEN not set; skipping chat.postMessage")
        return {"ok": False}

    payload: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SLACK_API}/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json=payload,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error("chat.postMessage failed: %s", data.get("error"))
        return data


async def post_response_url(response_url: str, *, blocks: list[dict[str, Any]], text: str = "FlowPilot update") -> None:
    """Post delayed response to slash command response_url."""
    payload = {
        "response_type": "in_channel",
        "replace_original": True,
        "blocks": blocks,
        "text": text,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(response_url, json=payload)
        if resp.status_code >= 400:
            logger.error("response_url post failed: %s %s", resp.status_code, resp.text)


async def respond_to_interaction(response_url: str, *, blocks: list[dict[str, Any]], text: str) -> None:
    payload = {
        "response_type": "in_channel",
        "replace_original": False,
        "blocks": blocks,
        "text": text,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(response_url, json=payload)
