import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    """Configure structlog for JSON-structured output keyed off LOG_LEVEL.

    Never logs secrets or raw Slack message content (Constitution IX; Tech Constraints).
    """
    logging.basicConfig(format="%(message)s", level=settings.log_level)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
