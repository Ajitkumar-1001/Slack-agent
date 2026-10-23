"""Single Slack grounding-context retrieval interface (Constitution VIII/IX; ADR-005).

No other module retrieves Slack context. Retrieved context is used for the active plan
then discarded — never persisted or indexed.
"""
import asyncio
from typing import Literal

import structlog
from pydantic import BaseModel
from slack_sdk.errors import SlackApiError

from slack.app import bolt_app

log = structlog.get_logger()

RetrievalMode = Literal["rts", "mock", "event_payload"]

# Same budget as the Drive adapter: this call sits on the approval-card critical path.
_TIMEOUT = 10

_MOCK_FIXTURE = [
    "[mock] The team agreed to launch the onboarding redesign in Q3.",
    "[mock] Design still needs an owner; the auth API is an external dependency.",
]


class RetrievalResult(BaseModel):
    messages: list[str]
    retrieval_mode: RetrievalMode


class _RtsMessage(BaseModel):
    content: str | None = None


class _RtsResults(BaseModel):
    messages: list[_RtsMessage]


class _RtsResponse(BaseModel):
    """Boundary model for the RTS response (Constitution VII). Extra fields are ignored; a
    missing or wrong-typed `results.messages` fails validation and triggers the fallback."""

    ok: Literal[True]
    results: _RtsResults


async def _rts_search(*, query: str, event: dict) -> list[str]:
    """The ONLY outbound network seam — the real Slack Real-Time Search API call.

    Calls `assistant.search.context` (docs.slack.dev/apis/web-api/real-time-search-api/).
    Bot-token calls require the `action_token` delivered on the triggering event.

    ponytail: response field names are sourced from Slack's public API docs, not verified
    against a live call (no RTS-enabled workspace available yet) — if the real response
    shape differs, `_RtsResponse` is the only place that needs adjusting.
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
    parsed = _RtsResponse.model_validate(response.data)
    return [m.content for m in parsed.results.messages if m.content]


def _event_payload(event: dict) -> RetrievalResult:
    text = event.get("text", "")
    return RetrievalResult(
        messages=[text] if text else [], retrieval_mode="event_payload"
    )


async def retrieve_context(*, query: str, event: dict, mode: str) -> RetrievalResult:
    if mode == "mock":
        result = RetrievalResult(messages=list(_MOCK_FIXTURE), retrieval_mode="mock")
    elif mode == "event_payload":
        result = _event_payload(event)
    else:
        try:
            messages = await asyncio.wait_for(
                _rts_search(query=query, event=event), _TIMEOUT
            )
            result = RetrievalResult(messages=messages, retrieval_mode="rts")
        except Exception as exc:
            # ADR-005: RTS unavailable -> ground only on the already-delivered event, never another
            # Slack query. Log type + Slack error code only: exception text can carry response
            # bodies, i.e. raw Slack content (IX).
            response = exc.response if isinstance(exc, SlackApiError) else {}
            log.warning(
                "slack_rts_unavailable",
                error_type=type(exc).__name__,
                slack_error=response.get("error"),
            )
            result = _event_payload(event)

    log.info(
        "slack_rts_retrieval",
        retrieval_mode=result.retrieval_mode,
        message_count=len(result.messages),
    )
    return result
