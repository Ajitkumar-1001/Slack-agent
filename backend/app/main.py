from fastapi import FastAPI

from app.logging import configure_logging
from app.routes.slack import router as slack_router


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="FlowPilot AI")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(slack_router)

    return app


app = create_app()
