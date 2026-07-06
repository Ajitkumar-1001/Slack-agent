"""Slack event handling: classify project-execution requests and route them (FR-001, FR-002)."""
from typing import Any

from slack.app import bolt_app
from workflows.create_plan import create_plan

# ponytail: keyword-intent heuristic for the MVP request gate (FR-002). Deterministic and
# offline-testable; upgrade to an LLM intent classifier if precision becomes an issue.
_PROJECT_SIGNALS = (
    "execution plan",
    "project plan",
    "plan for",
    "plan to launch",
    "launch",
    "milestone",
    "roadmap",
    "kickoff",
    "create github",
    "create issues",
    "execution",
)

_CLARIFICATION = (
    "I turn project goals into execution plans. Try: "
    '"@FlowPilot create an execution plan for the onboarding launch in four weeks."'
)


def classify_message(text: str) -> bool:
    """True if the message is a project-execution request."""
    lowered = text.lower()
    return any(signal in lowered for signal in _PROJECT_SIGNALS)


async def _route(event: dict, say: Any) -> None:
    text = event.get("text", "")
    if classify_message(text):
        await create_plan(event=event, say=say)
    else:
        await say(text=_CLARIFICATION)


@bolt_app.event("app_mention")
async def handle_app_mention(event: dict, say: Any) -> None:
    await _route(event, say)


@bolt_app.event("message")
async def handle_message(event: dict, say: Any) -> None:
    # ignore bot echoes and message subtypes (edits, joins, etc.)
    if event.get("subtype") or event.get("bot_id"):
        return
    await _route(event, say)
