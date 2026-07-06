"""Single Slack grounding-context retrieval interface (Constitution VIII/IX; ADR-005).

No other module retrieves Slack context. Retrieved context is used for the active plan
then discarded — never persisted or indexed.
"""
from typing import Literal

import structlog
from pydantic import BaseModel

log = structlog.get_logger()

RetrievalMode = Literal["rts", "mock", "event_payload"]

_MOCK_FIXTURE = [
    "[mock] The team agreed to launch the onboarding redesign in Q3.",
    "[mock] Design still needs an owner; the auth API is an external dependency.",
]


class RetrievalResult(BaseModel):
    messages: list[str]
    retrieval_mode: RetrievalMode


async def _rts_search(query: str) -> list[str]:
    """The ONLY outbound network seam — the real Slack Real-Time Search API call.

    ponytail: production RTS call is stubbed. The demo/test paths (mock, event_payload)
    are fully functional per ADR-005; wire this to the live Slack RTS API once a workspace
    with RTS enabled is available (research.md flagged confirming its exact field names here).
    """
    raise NotImplementedError(
        "Slack RTS production call not yet wired; use mode='mock' or 'event_payload' (ADR-005)"
    )


async def retrieve_context(*, query: str, event: dict, mode: str) -> RetrievalResult:
    if mode == "mock":
        result = RetrievalResult(messages=list(_MOCK_FIXTURE), retrieval_mode="mock")
    elif mode == "event_payload":
        text = event.get("text", "")
        result = RetrievalResult(
            messages=[text] if text else [], retrieval_mode="event_payload"
        )
    else:
        result = RetrievalResult(messages=await _rts_search(query), retrieval_mode="rts")

    log.info(
        "slack_rts_retrieval",
        retrieval_mode=result.retrieval_mode,
        message_count=len(result.messages),
    )
    return result
