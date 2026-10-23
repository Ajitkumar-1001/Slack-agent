"""T017 [US1] — request-classification test (FR-002, SC-005).

RED until T024 creates backend/slack/events.py.

Interface imposed on T024:
- ``classify_message(text: str) -> bool`` (True = a project-execution request).
  Must be deterministic / offline-testable for clear cases (a keyword/intent heuristic is
  fine for the MVP; if LLM-backed, expose a mockable seam). A False result is what gates
  the handler into the clarification reply and prevents any ProjectProposal from being created.
"""

import pytest


@pytest.mark.parametrize(
    "text",
    [
        "hey, does anyone want to grab lunch?",
        "lunch launch party pics",
        "<@UBOT> lunch launch party pics",
        "the launch went great, congrats team!",
        "what's the plan for lunch?",
        "did you see the execution of that play",
        "can someone launch the build?",
        "release party pics from the launch",
    ],
)
def test_non_project_message_is_not_a_request(text):
    from slack.events import classify_message

    assert classify_message(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "create an execution plan for the onboarding launch in four weeks",
        "<@UBOT> create an execution plan for our onboarding redesign launch.",
        "<@UBOT> launch our customer onboarding redesign in four weeks.",
        "Plan the API migration and create the task breakdown.",
        "Create a project plan from this thread.",
        "Create GitHub issues from this approved plan.",
        "please plan the onboarding launch",
        "we need a launch plan for billing v2",
    ],
)
def test_project_execution_request_is_classified(text):
    from slack.events import classify_message

    assert classify_message(text) is True


def test_suggested_prompts_are_themselves_project_requests():
    # FR-014 prompts offered in the FR-002 clarification must pass the gate they advertise.
    from slack.events import _SUGGESTED_PROMPTS, classify_message

    assert _SUGGESTED_PROMPTS
    assert all(classify_message(f"<@UBOT> {p}") for p in _SUGGESTED_PROMPTS)


@pytest.mark.asyncio
async def test_non_project_mention_gets_clarification_and_no_plan(monkeypatch):
    from slack.events import _SUGGESTED_PROMPTS, handle_app_mention

    calls = _count_plans(monkeypatch)
    said: list[dict] = []

    async def say(**kwargs: object) -> None:
        said.append(kwargs)

    event = {
        "type": "app_mention",
        "text": "<@UBOT> lunch launch party pics",
        "user": "U1",
        "channel": "C1",
        "ts": "1.2",
    }
    await handle_app_mention(event=event, say=say)

    assert calls == []
    assert len(said) == 1
    assert all(p in str(said[0]["text"]) for p in _SUGGESTED_PROMPTS)


# NFR-001: one Slack message must produce exactly one plan, regardless of how many event types
# Slack delivers it as.

_REQUEST = "<@UBOT> create an execution plan for the onboarding launch in four weeks"


async def _say(**_: object) -> None:
    pass


def _count_plans(monkeypatch) -> list[dict]:
    import slack.events as ev

    calls: list[dict] = []

    async def fake_create_plan(*, event: dict, say: object) -> None:
        calls.append(event)

    monkeypatch.setattr(ev, "create_plan", fake_create_plan)
    return calls


@pytest.mark.asyncio
async def test_channel_mention_delivered_twice_creates_one_plan(monkeypatch):
    from slack.events import handle_app_mention, handle_message

    calls = _count_plans(monkeypatch)
    said: list[dict] = []

    async def say(**kwargs: object) -> None:
        said.append(kwargs)

    base = {"text": _REQUEST, "user": "U1", "channel": "C1", "ts": "1.2"}
    await handle_app_mention(event={**base, "type": "app_mention"}, say=say)
    await handle_message(
        event={**base, "type": "message", "channel_type": "channel"}, say=say
    )

    assert len(calls) == 1
    # the duplicate message event posts nothing (no second card, no clarification)
    assert said == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra", [{}, {"thread_ts": "1.0"}], ids=["dm", "assistant_thread"]
)
async def test_dm_and_assistant_thread_messages_still_create_a_plan(monkeypatch, extra):
    from slack.events import handle_message

    calls = _count_plans(monkeypatch)
    event = {
        "type": "message",
        "channel_type": "im",
        "text": _REQUEST,
        "channel": "D1",
        "ts": "1.2",
    }
    await handle_message(event={**event, **extra}, say=_say)

    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"subtype": "message_changed"}, {"bot_id": "B1"}])
async def test_dm_bot_echoes_and_subtypes_are_ignored(monkeypatch, extra):
    from slack.events import handle_message

    calls = _count_plans(monkeypatch)
    event = {
        "type": "message",
        "channel_type": "im",
        "text": _REQUEST,
        "channel": "D1",
        "ts": "1.2",
    }
    await handle_message(event={**event, **extra}, say=_say)

    assert calls == []
