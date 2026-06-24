"""Slack request signature verification."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)


async def verify_slack_request(request: Request) -> bytes:
    """
    Verify Slack signing secret per
    https://api.slack.com/authentication/verifying-requests-from-slack
  """
    settings = get_settings()
    body = await request.body()

    if not settings.slack_signing_secret:
        if settings.app_env == "development":
            logger.warning("SLACK_SIGNING_SECRET not set — skipping verification in development")
            return body
        raise HTTPException(status_code=500, detail="Slack signing secret not configured")

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    if abs(time.time() - int(timestamp)) > 60 * 5:
        raise HTTPException(status_code=401, detail="Stale Slack request")

    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(),
            basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    return body
