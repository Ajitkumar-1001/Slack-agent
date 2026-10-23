"""Slack event handling: classify project-execution requests and route them (FR-001, FR-002)."""

import re
from typing import Any

from slack.app import bolt_app
from workflows.create_plan import create_plan

# ponytail: deterministic token heuristic for the FR-002 request gate, not a parser. A request is
# an explicit planning phrase, or an action verb followed within a few words by a planning noun,
# so a stray "launch" no longer counts. Ceiling: "plan a launch party" still passes; swap in an
# LLM intent classifier if precision becomes an issue.
# <@U123> mentions, <#C123|chan> and <https://…> links are markup, not request text
_SLACK_MARKUP = re.compile(r"<[^>]*>")
_EXPLICIT_PHRASE = re.compile(
    r"\b(?:execution|project|launch|rollout|release|migration)\s+plans?\b|\btask\s+breakdown\b"
)
_ACTION_VERBS = frozenset(
    "create draft build generate prepare outline plan launch ship kick roll break turn scope".split()
)
_PLANNING_NOUNS = frozenset(
    "plan roadmap milestone milestones timeline task tasks project launch rollout release "
    "migration redesign initiative issues tickets breakdown".split()
)
_VERB_NOUN_WINDOW = 5

_SUGGESTED_PROMPTS = (
    "create an execution plan for the onboarding launch in four weeks",
    "plan the API migration and break it into GitHub issues",
    "create a project plan from this thread",
)
_CLARIFICATION = "\n".join(
    [
        "I turn project goals into execution plans, but that didn't look like a planning "
        "request. Try one of these:",
        *(f"• `@FlowPilot {prompt}`" for prompt in _SUGGESTED_PROMPTS),
    ]
)


def classify_message(text: str) -> bool:
    """True if the message is a project-execution request."""
    lowered = _SLACK_MARKUP.sub(" ", text).lower()
    if _EXPLICIT_PHRASE.search(lowered):
        return True
    words = re.findall(r"[a-z0-9]+", lowered)
    # the noun must come after the verb, so one ambiguous word ("launch") can't fill both roles
    return any(
        word in _ACTION_VERBS
        and not _PLANNING_NOUNS.isdisjoint(words[i + 1 : i + 1 + _VERB_NOUN_WINDOW])
        for i, word in enumerate(words)
    )


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
    # NFR-001: channel @mentions also arrive as app_mention; handling them here too would create
    # a second plan + card. Only DMs and Assistant threads (both channel_type "im") route here.
    if event.get("channel_type") != "im":
        return
    await _route(event, say)
