"""NFR-001 — tools/retry.py: bounded retry with backoff for transient external-call failures.

Fake ``send`` callables / ``httpx.MockTransport`` clients and a recorded sleep — nothing really
sleeps or touches the network.
"""

import email.utils
import time

import httpx
import pytest

import tools.retry as retry
from app.config import settings
from tools import github, google_drive, jira, notion

_REQ = httpx.Request("GET", "https://api.example.test/x")


def _resp(status: int, **headers: str) -> httpx.Response:
    return httpx.Response(status, headers=headers, request=_REQ)


def _scripted(*outcomes):
    """A send() returning/raising each outcome in turn; a call past the script fails the test."""
    calls = []

    async def send():
        outcome = outcomes[len(calls)]
        calls.append(outcome)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return send, calls


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []

    async def fake_sleep(delay):
        recorded.append(delay)

    monkeypatch.setattr(retry, "_sleep", fake_sleep)
    return recorded


@pytest.mark.asyncio
async def test_read_retries_5xx_with_exponential_jittered_backoff(sleeps):
    send, calls = _scripted(_resp(503), _resp(502), _resp(200))

    response = await retry.send_with_retry(send, retry_5xx=True)

    assert response.status_code == 200
    assert len(calls) == 3
    assert 0.25 <= sleeps[0] <= 0.5
    assert 0.5 <= sleeps[1] <= 1.0


@pytest.mark.asyncio
async def test_attempts_are_bounded_at_three_and_last_response_is_returned(sleeps):
    send, calls = _scripted(_resp(503), _resp(503), _resp(503))

    response = await retry.send_with_retry(send, retry_5xx=True)

    assert response.status_code == 503  # caller's raise_for_status() surfaces it
    assert len(calls) == 3
    assert len(sleeps) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_5xx", [True, False])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
async def test_4xx_other_than_429_is_never_retried(sleeps, status, retry_5xx):
    send, calls = _scripted(_resp(status))

    response = await retry.send_with_retry(send, retry_5xx=retry_5xx)

    assert response.status_code == status
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_write_is_not_resent_on_5xx_so_a_hidden_success_cannot_duplicate(sleeps):
    send, calls = _scripted(_resp(500))

    response = await retry.send_with_retry(send, retry_5xx=False)

    assert response.status_code == 500
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_write_retries_429_honouring_retry_after_seconds(sleeps):
    send, calls = _scripted(_resp(429, **{"Retry-After": "2"}), _resp(201))

    response = await retry.send_with_retry(send, retry_5xx=False)

    assert response.status_code == 201
    assert len(calls) == 2
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_write_retries_connect_error_since_the_request_never_reached_the_server(
    sleeps,
):
    send, calls = _scripted(httpx.ConnectError("refused"), _resp(201))

    response = await retry.send_with_retry(send, retry_5xx=False)

    assert response.status_code == 201
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_connect_error_on_every_attempt_is_raised_after_three(sleeps):
    send, calls = _scripted(*(httpx.ConnectError("refused") for _ in range(3)))

    with pytest.raises(httpx.ConnectError):
        await retry.send_with_retry(send, retry_5xx=True)
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("t"), httpx.ConnectTimeout("t"), httpx.ReadError("reset")]
)
async def test_timeouts_and_mid_flight_errors_are_not_retried(sleeps, exc):
    send, calls = _scripted(exc)

    with pytest.raises(type(exc)):
        await retry.send_with_retry(send, retry_5xx=True)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_after_http_date_is_honoured(sleeps):
    when = email.utils.formatdate(time.time() + 3, usegmt=True)
    send, _ = _scripted(_resp(503, **{"Retry-After": when}), _resp(200))

    await retry.send_with_retry(send, retry_5xx=True)

    assert 1.0 < sleeps[0] <= 3.0


@pytest.mark.asyncio
async def test_retry_after_beyond_cap_gives_up_instead_of_blocking(sleeps):
    send, calls = _scripted(_resp(429, **{"Retry-After": "60"}))

    response = await retry.send_with_retry(send, retry_5xx=True)

    assert response.status_code == 429
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_unparseable_retry_after_falls_back_to_backoff(sleeps):
    send, _ = _scripted(_resp(429, **{"Retry-After": "soon"}), _resp(200))

    await retry.send_with_retry(send, retry_5xx=True)

    assert 0.25 <= sleeps[0] <= 0.5


# ---- adapter wiring: reads resend on 5xx, creates never do ----

_OK_BODY = {
    "number": 1,
    "html_url": "u",
    "key": "K-1",
    "id": "p",
    "url": "u",
    "items": [],
    "issues": [],
    "results": [],
    "files": [],
}
_DOC = "application/vnd.google-apps.document"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call, is_read",
    [
        (lambda: github.github_create_issue({"title": "t", "body": "b"}), False),
        (lambda: github.github_find_issue("k"), True),
        (lambda: jira.jira_create_ticket({"fields": {}}), False),
        (lambda: jira.jira_find_ticket("k"), True),
        (lambda: notion.notion_create_page({"parent": {}}), False),
        (lambda: notion.notion_find_page("k"), True),
        (
            lambda: google_drive._search_files(query="q", folder_scope=None, token="t"),
            True,
        ),
        (
            lambda: google_drive._export_file(file_id="f", mime_type=_DOC, token="t"),
            True,
        ),
    ],
    ids=[
        "github_create",
        "github_find",
        "jira_create",
        "jira_find",
        "notion_create",
        "notion_find",
        "drive_search",
        "drive_export",
    ],
)
async def test_adapters_resend_reads_but_never_creates_on_5xx(
    monkeypatch, sleeps, call, is_read
):
    monkeypatch.setattr(settings, "jira_base_url", "https://jira.example.test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503 if len(requests) == 1 else 200, json=_OK_BODY)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )

    if is_read:
        await call()
        assert len(requests) == 2
    else:
        with pytest.raises(httpx.HTTPStatusError):
            await call()
        assert len(requests) == 1
