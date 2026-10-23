"""Static checks on the container image (005 contracts/docker-image.md). Docker can't run in the
test suite, so pin the invariants a broken Dockerfile/.dockerignore would otherwise only reveal
at `docker run`."""

import fnmatch
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _instructions(name: str) -> list[str]:
    lines = (BACKEND / "Dockerfile").read_text().splitlines()
    return [
        line.removeprefix(f"{name} ") for line in lines if line.startswith(f"{name} ")
    ]


def test_image_migrates_then_execs_uvicorn_as_non_root():
    assert _instructions("USER")[-1] == "nonroot"
    (cmd,) = _instructions("CMD")
    assert json.loads(cmd) == [
        "/app/.venv/bin/uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    (entrypoint,) = _instructions("ENTRYPOINT")
    _shell, _flag, script, argv0 = json.loads(entrypoint)
    assert script.startswith("/app/.venv/bin/alembic upgrade head && ")
    assert script.endswith('exec "$@"')  # exec: uvicorn becomes PID 1; "$@" is CMD
    assert argv0  # fills $0 — without it "$@" silently drops CMD's first argument


def _dockerignored(path: str) -> bool:
    lines = (BACKEND / ".dockerignore").read_text().splitlines()
    patterns = [
        line.strip().strip("/")
        for line in lines
        if line.strip() and not line.startswith("#")
    ]
    parts = path.split("/")
    # Check every parent too: an ignored directory drops everything under it.
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return any(fnmatch.fnmatchcase(p, pat) for p in prefixes for pat in patterns)


def test_build_context_keeps_migrations_and_drops_secrets():
    for needed in (
        "alembic.ini",
        "db/migrations/env.py",
        "db/migrations/versions/0001_initial.py",
        "app/main.py",
        "pyproject.toml",
        "uv.lock",
    ):
        assert (BACKEND / needed).exists(), needed
        assert not _dockerignored(needed), needed
    for excluded in (
        ".env",
        ".venv/bin/python",
        "tests/test_health.py",
        "app/__pycache__/main.cpython-312.pyc",
    ):
        assert _dockerignored(excluded), excluded
