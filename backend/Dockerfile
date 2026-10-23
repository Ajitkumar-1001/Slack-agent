# Contract: .specify/specs/005-flowpilot-devops-foundation/contracts/docker-image.md
# Build from the repo root: docker build -f backend/Dockerfile -t flowpilot-ai-backend backend
# No secret is needed to build; all config arrives as env vars at `docker run` time.

FROM python:3.12.13-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_NO_DEV=1
WORKDIR /app

# Dependencies first, so this layer stays cached until the lockfile changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project --no-editable

COPY . .
RUN uv sync --locked --no-editable


FROM python:3.12.13-slim-bookworm
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --no-create-home nonroot
WORKDIR /app
# All of /app, not just .venv: this is a virtual uv project (no [build-system]), so the app
# packages, alembic.ini and db/migrations live beside the venv rather than inside it.
COPY --from=builder --chown=nonroot:nonroot /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER nonroot
EXPOSE 8000

# Apply migrations before serving, then exec so uvicorn replaces the shell as PID 1 and gets
# SIGTERM directly ("sh" fills $0 so "$@" is exactly CMD). Missing config or an unreachable DB
# fails the migration and exits non-zero instead of serving a half-configured process.
# ponytail: migrate-on-start assumes one replica; move to a one-off job if we ever scale out.
ENTRYPOINT ["/bin/sh", "-c", "/app/.venv/bin/alembic upgrade head && exec \"$@\"", "sh"]
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
