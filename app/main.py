"""FlowPilot AI — FastAPI application entry point."""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.projects import router as projects_router
from app.config import get_settings
from app.models.schemas import HealthResponse
from app.slack.handlers import router as slack_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FlowPilot AI",
    description="Slack-native autonomous project execution agent",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(slack_router)
app.include_router(projects_router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        slack_configured=settings.slack_configured,
        db_configured=settings.db_configured,
    )


@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "FlowPilot AI v%s starting (env=%s, slack=%s, db=%s)",
        __version__,
        settings.app_env,
        settings.slack_configured,
        settings.db_configured,
    )
