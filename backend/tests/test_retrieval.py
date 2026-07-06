"""T014 [US1] — Slack RTS retrieval tests (Constitution VIII/IX; ADR-005).

RED until T022 creates backend/tools/slack_rts.py.

Interface imposed on T022:
- ``async retrieve_context(*, query: str, event: dict, mode: str) -> Result`` where
  ``Result`` has ``.retrieval_mode: str`` and ``.messages: list[str]``.
- The ONLY outbound-network seam is ``tools.slack_rts._rts_search`` (the real RTS call).
  ``mock`` and ``event_payload`` modes MUST NOT call it — that is how "zero network"
  and "no additional Slack API call" are enforced without coupling to the HTTP client.
"""
import pytest


def _boom(*args, **kwargs):
    raise AssertionError("fallback modes must not make any network / Slack call")


@pytest.mark.asyncio
async def test_mock_mode_makes_zero_network_calls(monkeypatch):
    import tools.slack_rts as rts

    monkeypatch.setattr(rts, "_rts_search", _boom)
    result = await rts.retrieve_context(query="launch plan", event={}, mode="mock")

    assert result.retrieval_mode == "mock"
    assert isinstance(result.messages, list)


@pytest.mark.asyncio
async def test_event_payload_mode_uses_only_event_and_no_slack_calls(monkeypatch):
    import tools.slack_rts as rts

    monkeypatch.setattr(rts, "_rts_search", _boom)
    event = {"text": "please plan the onboarding launch", "channel": "C1", "ts": "1.2"}
    result = await rts.retrieve_context(query="onboarding", event=event, mode="event_payload")

    assert result.retrieval_mode == "event_payload"
    # grounded only on the delivered event's own text
    assert any("onboarding launch" in m for m in result.messages)


@pytest.mark.asyncio
async def test_retrieval_mode_is_always_a_valid_label(monkeypatch):
    import tools.slack_rts as rts

    monkeypatch.setattr(rts, "_rts_search", _boom)
    result = await rts.retrieve_context(query="x", event={"text": "y"}, mode="mock")
    assert result.retrieval_mode in {"rts", "mock", "event_payload"}
