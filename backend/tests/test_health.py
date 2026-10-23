import asyncio
import contextlib
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

import app.main as main_module
from app.main import app


def test_health_returns_ok_when_db_reachable(monkeypatch):
    async def fake_check() -> bool:
        return True

    monkeypatch.setattr(main_module, "check_database", fake_check)
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_reports_db_unreachable(monkeypatch):
    async def fake_check() -> bool:
        return False

    monkeypatch.setattr(main_module, "check_database", fake_check)
    response = TestClient(app).get("/health")

    assert response.status_code == 200  # never 503 — the outage is in the body only
    assert response.json() == {"status": "ok", "db": "unreachable"}


@pytest.mark.asyncio
async def test_check_database_true_when_select_1_succeeds(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(main_module, "engine", engine)
    try:
        assert await main_module.check_database() is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_check_database_false_on_connection_error(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:////nonexistent-dir/flowpilot.db")
    monkeypatch.setattr(main_module, "engine", engine)
    try:
        assert await main_module.check_database() is False
    finally:
        await engine.dispose()


class _HangingEngine:
    @contextlib.asynccontextmanager
    async def connect(self):
        await asyncio.sleep(60)
        yield


@pytest.mark.asyncio
async def test_check_database_false_on_timeout_without_hanging(monkeypatch):
    monkeypatch.setattr(main_module, "engine", _HangingEngine())
    monkeypatch.setattr(main_module, "DB_HEALTH_TIMEOUT_SECONDS", 0.05)

    start = time.monotonic()
    assert await main_module.check_database() is False
    assert time.monotonic() - start < 1.0
