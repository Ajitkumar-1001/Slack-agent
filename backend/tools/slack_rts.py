"""Single Slack grounding-context retrieval interface (Constitution VIII/IX; ADR-005).

No other module retrieves Slack context. Retrieved context is used for the active plan
then discarded — never persisted or indexed.
"""
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from slack.app import bolt_app

log = structlog.get_logger()

RetrievalMode = Literal["rts", "mock", "event_payload"]

_MOCK_FIXTURE = [
    "[mock] The team agreed to launch the onboarding redesign in Q3.",
    "[mock] Design still needs an owner; the auth API is an external dependency.",
]


class RetrievalResult(BaseModel):
    messages: list[str]
    retrieval_mode: RetrievalMode


async def _rts_search(*, query: str, event: dict) -> list[str]:
    """The ONLY outbound network seam — the real Slack Real-Time Search API call.

    Calls `assistant.search.context` (docs.slack.dev/apis/web-api/real-time-search-api/).
    Bot-token calls require the `action_token` delivered on the triggering event.

    ponytail: response field names are sourced from Slack's public API docs, not verified
    against a live call (no RTS-enabled workspace available yet) — if the real response
    shape differs, this is the only place that needs adjusting.
    """
    response = await bolt_app.client.api_call(
        "assistant.search.context",
        json={
            "query": query,
            "action_token": event.get("action_token"),
            "content_types": ["messages"],
            "channel_types": ["public_channel", "private_channel", "mpim", "im"],
            "limit": 20,
        },
    )
    results: dict[str, Any] = response.get("results") or {}
    messages: list[dict[str, Any]] = results.get("messages") or []
    return [m["content"] for m in messages if m.get("content")]


async def retrieve_context(*, query: str, event: dict, mode: str) -> RetrievalResult:
    if mode == "mock":
        result = RetrievalResult(messages=list(_MOCK_FIXTURE), retrieval_mode="mock")
    elif mode == "event_payload":
        text = event.get("text", "")
        result = RetrievalResult(
            messages=[text] if text else [], retrieval_mode="event_payload"
        )
    else:
        result = RetrievalResult(
            messages=await _rts_search(query=query, event=event), retrieval_mode="rts"
        )

    log.info(
        "slack_rts_retrieval",
        retrieval_mode=result.retrieval_mode,
        message_count=len(result.messages),
    )
    return result
