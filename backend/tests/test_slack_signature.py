"""NFR-003 / Constitution V — Slack request signature verification on both Slack routes.

Every request is driven through the real FastAPI routes -> Bolt handler. Valid requests are
signed with ``settings.slack_signing_secret``, which under the test suite is conftest's
``test-signing-secret``. Bodies are signed and sent as the exact same raw bytes.
"""

import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from slack_sdk.signature import SignatureVerifier

from app.config import settings
from app.main import app

ROUTES = ["/slack/events", "/slack/actions"]
STALE_TIMESTAMP = "1600000000"  # 2020 — far outside Slack's 5-minute replay window

# Realistic per-route payloads for the rejection cases (rejected before auth.test, so offline).
_APP_MENTION = json.dumps(
    {
        "type": "event_callback",
        "team_id": "T1",
        "event": {
            "type": "app_mention",
            "user": "U1",
            "channel": "C1",
            "ts": "1.2",
            "text": "<@UBOT> create an execution plan for the onboarding launch in four weeks",
        },
    }
)
_BLOCK_ACTIONS = urlencode(
    {
        "payload": json.dumps(
            {
                "type": "block_actions",
                "team": {"id": "T1"},
                "user": {"id": "U1"},
                "actions": [{"action_id": "reject_plan", "value": "proposal-1"}],
            }
        )
    }
)
REALISTIC = {
    "/slack/events": (_APP_MENTION, "application/json"),
    "/slack/actions": (_BLOCK_ACTIONS, "application/x-www-form-urlencoded"),
}


def _post(
    route: str,
    body: str,
    content_type: str,
    *,
    secret: str | None = None,
    timestamp: str | None = None,
    signature: str | None = None,
):
    timestamp = timestamp or str(int(time.time()))
    if signature is None:
        signature = SignatureVerifier(
            secret or settings.slack_signing_secret
        ).generate_signature(timestamp=timestamp, body=body)
    headers = {
        "Content-Type": content_type,
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature or "",
    }
    return TestClient(app).post(route, content=body.encode(), headers=headers)


@pytest.fixture
def handler_calls(monkeypatch) -> list[str]:
    """Spies on what a request would reach past verification on each route."""
    import slack.actions as actions
    import slack.events as events

    calls: list[str] = []

    async def fake_create_plan(**_: object) -> None:
        calls.append("create_plan")

    async def fake_reject_plan(**_: object) -> None:
        calls.append("reject_plan")

    monkeypatch.setattr(events, "create_plan", fake_create_plan)
    monkeypatch.setattr(actions, "reject_plan", fake_reject_plan)
    return calls


# Slack only sends url_verification to the Events URL; posting it to /slack/actions too is a
# network-free proof that the same signature gate (which runs before URL verification) passes there.
@pytest.mark.parametrize("route", ROUTES)
def test_valid_signature_is_accepted_and_url_verification_echoes_challenge(route):
    body = json.dumps(
        {"type": "url_verification", "token": "t", "challenge": "challenge-abc"}
    )

    response = _post(route, body, "application/json")

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-abc"}


@pytest.mark.parametrize("route", ROUTES)
def test_url_verification_with_invalid_signature_gets_no_challenge(route):
    body = json.dumps(
        {"type": "url_verification", "token": "t", "challenge": "challenge-abc"}
    )

    response = _post(route, body, "application/json", secret="wrong-test-secret")

    assert response.status_code == 401
    assert "challenge-abc" not in response.text


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    "sign",
    [{"secret": "wrong-test-secret"}, {"signature": ""}],
    ids=["wrong_secret", "missing"],
)
def test_invalid_signature_is_rejected_before_any_handler(route, sign, handler_calls):
    body, content_type = REALISTIC[route]

    response = _post(route, body, content_type, **sign)

    assert response.status_code == 401
    assert response.json() == {"error": "invalid request"}
    assert handler_calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_stale_timestamp_is_rejected_even_when_correctly_signed(route, handler_calls):
    body, content_type = REALISTIC[route]

    response = _post(route, body, content_type, timestamp=STALE_TIMESTAMP)

    assert response.status_code == 401
    assert response.json() == {"error": "invalid request"}
    assert handler_calls == []
