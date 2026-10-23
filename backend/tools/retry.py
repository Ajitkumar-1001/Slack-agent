"""Bounded retry with exponential backoff + jitter for transient external-call failures (NFR-001).

Shared by the httpx adapters in tools/. Anthropic (SDK default max_retries=2) and google-auth's
token refresh already retry on their own, so they are deliberately not wrapped here.

Retried: 429, `httpx.ConnectError`, and — only when ``retry_5xx`` — 5xx. Never other 4xx, and
never timeouts (each attempt already spent the full timeout budget; Drive's sits on the
approval-card critical path).
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
import structlog

log = structlog.get_logger()

_ATTEMPTS = 3
_BASE_DELAY = 0.5
_MAX_DELAY = 8.0  # longest we block on one Retry-After; a longer ask gives up instead

_sleep = asyncio.sleep  # module-level so tests can patch it out


def _retry_after(response: httpx.Response) -> float | None:
    """Retry-After as seconds (delta-seconds or HTTP-date form); None if absent/unparseable."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(
            0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        )
    except (TypeError, ValueError):
        return None


async def send_with_retry(
    send: Callable[[], Awaitable[httpx.Response]], *, retry_5xx: bool
) -> httpx.Response:
    """Call ``send`` up to 3 times and return the last response — the caller still calls
    ``raise_for_status()``. Pass ``retry_5xx=False`` for non-idempotent creates: a 429 or a
    refused connection means the request was never processed, but a 5xx may hide a write that
    succeeded, so resending it could duplicate."""
    for attempt in range(_ATTEMPTS - 1):
        backoff = _BASE_DELAY * 2**attempt * random.uniform(0.5, 1.0)
        status: int | None = None
        try:
            response = await send()
        except httpx.ConnectError:
            delay = backoff
        else:
            status = response.status_code
            if status != 429 and not (retry_5xx and status >= 500):
                return response
            retry_after = _retry_after(response)
            if retry_after is not None and retry_after > _MAX_DELAY:
                return response
            delay = backoff if retry_after is None else retry_after
        # Status + attempt only: URLs/bodies can carry request text derived from Slack (IX).
        log.warning(
            "external_call_retry", attempt=attempt + 1, status_code=status, delay=delay
        )
        await _sleep(delay)
    return await send()
