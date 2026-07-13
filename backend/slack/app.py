from slack_bolt.async_app import AsyncApp

from app.config import settings

# AsyncApp verifies request signatures and handles URL verification by default
# (request_verification_enabled / url_verification_enabled default True — Constitution V).
# It performs no auth.test network call at construction, so it is import-safe.
bolt_app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)
