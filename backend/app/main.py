import asyncio

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.logging import configure_logging
from app.routes.slack import router as slack_router
from db.session import engine

DB_HEALTH_TIMEOUT_SECONDS = 2.0


async def check_database() -> bool:
    async def _ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=DB_HEALTH_TIMEOUT_SECONDS)
        return True
    except (SQLAlchemyError, OSError, TimeoutError):
        return False


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="FlowPilot AI")

    @app.get("/health")
    async def health() -> dict[str, str]:
        # Always 200: a DB outage shows in the body, never the status code (contracts/health-check.md).
        return {"status": "ok", "db": "ok" if await check_database() else "unreachable"}

    app.include_router(slack_router)

    return app


app = create_app()
