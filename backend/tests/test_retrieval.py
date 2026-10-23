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


_SECRET = "confidential roadmap detail"

# Documented assistant.search.context shape; extra per-message fields must be ignored.
_RTS_FIXTURE = {
    "ok": True,
    "results": {
        "messages": [
            {
                "author_name": "Ana",
                "channel_id": "C1",
                "message_ts": "1.1",
                "permalink": "https://example.slack.com/archives/C1/p11",
                "content": "We committed to a Q3 launch.",
            },
            {"channel_id": "C2", "message_ts": "1.2", "content": ""},
            {"channel_id": "C3", "message_ts": "1.3", "content": None},
            {"channel_id": "C4", "message_ts": "1.4"},
        ]
    },
    "response_metadata": {"next_cursor": ""},
}


def _slack_response(data):
    from slack_sdk.web.async_slack_response import AsyncSlackResponse

    return AsyncSlackResponse(
        client=None,
        http_verb="POST",
        api_url="",
        req_args={},
        data=data,
        headers={},
        status_code=200,
    )


def _fake_bolt(*, data=None, exc=None, captured=None):
    """A Bolt app whose client returns ``data`` as a real AsyncSlackResponse (or raises ``exc``)."""

    class _FakeClient:
        async def api_call(self, method, json):
            if captured is not None:
                captured.update(method=method, json=json)
            if exc is not None:
                raise exc
            return _slack_response(data)

    class _FakeBoltApp:
        client = _FakeClient()

    return _FakeBoltApp()


@pytest.mark.asyncio
async def test_rts_mode_parses_documented_response(monkeypatch):
    import tools.slack_rts as rts

    captured: dict = {}
    fake = _fake_bolt(data=_RTS_FIXTURE, captured=captured)
    monkeypatch.setattr(rts, "bolt_app", fake)
    event = {"text": "plan it", "action_token": "AT123"}
    result = await rts.retrieve_context(query="plan it", event=event, mode="rts")

    assert result.retrieval_mode == "rts"
    # empty / null / missing content is dropped; extra per-message fields are ignored
    assert result.messages == ["We committed to a Q3 launch."]
    assert captured["method"] == "assistant.search.context"
    assert captured["json"]["query"] == "plan it"
    assert captured["json"]["action_token"] == "AT123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        {"ok": True},  # no results
        {"ok": True, "results": {"messages": _SECRET}},  # messages not a list
        {"ok": True, "results": {"messages": [_SECRET]}},  # message not an object
        # content not a string
        {"ok": True, "results": {"messages": [{"content": [_SECRET]}]}},
        {"results": {"messages": [{"content": _SECRET}]}},  # no Slack `ok` envelope
        _SECRET.encode(),  # binary body
    ],
)
async def test_rts_malformed_response_falls_back_to_event_payload(monkeypatch, data):
    """Constitution VII: a response failing validation is a safe failure (ADR-005 fallback),
    never best-effort parsing — and the fallback log never says ``rts`` or leaks content."""
    import tools.slack_rts as rts
    from structlog.testing import capture_logs

    monkeypatch.setattr(rts, "bolt_app", _fake_bolt(data=data))
    event = {"text": "plan the onboarding launch"}
    with capture_logs() as logs:
        result = await rts.retrieve_context(query="onboarding", event=event, mode="rts")

    assert result.retrieval_mode == "event_payload"
    assert result.messages == ["plan the onboarding launch"]
    modes = [e["retrieval_mode"] for e in logs if e["event"] == "slack_rts_retrieval"]
    assert modes == ["event_payload"]  # never "rts" during fallback (ADR-005)
    assert any(e["event"] == "slack_rts_unavailable" for e in logs)
    assert _SECRET not in repr(logs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "slack_error"),
    [
        ("slack_api_error", "missing_scope"),
        (ConnectionError("network down"), None),
    ],
)
async def test_rts_call_failure_falls_back_to_event_payload(
    monkeypatch, exc, slack_error
):
    import tools.slack_rts as rts
    from slack_sdk.errors import SlackApiError
    from structlog.testing import capture_logs

    if exc == "slack_api_error":
        body = {"ok": False, "error": "missing_scope", "detail": _SECRET}
        exc = SlackApiError("failed", _slack_response(body))
    monkeypatch.setattr(rts, "bolt_app", _fake_bolt(exc=exc))
    event = {"text": "plan it"}
    with capture_logs() as logs:
        result = await rts.retrieve_context(query="q", event=event, mode="rts")

    assert result.retrieval_mode == "event_payload"
    assert result.messages == ["plan it"]
    unavailable = [e for e in logs if e["event"] == "slack_rts_unavailable"]
    assert unavailable and unavailable[0]["slack_error"] == slack_error
    assert _SECRET not in repr(logs)


@pytest.mark.asyncio
async def test_rts_timeout_falls_back_to_event_payload(monkeypatch):
    import asyncio

    import tools.slack_rts as rts

    async def hang(**kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(rts, "_rts_search", hang)
    monkeypatch.setattr(rts, "_TIMEOUT", 0.01)
    event = {"text": "plan it"}
    result = await rts.retrieve_context(query="q", event=event, mode="rts")

    assert result.retrieval_mode == "event_payload"
    assert result.messages == ["plan it"]
