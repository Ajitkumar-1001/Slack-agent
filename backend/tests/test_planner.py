"""T015 [US1] — planner validation / retry-once / safe-fail tests (Constitution VII; AC-010).

RED until T021 creates backend/agents/planner.py.

Interface imposed on T021:
- ``async generate_plan(*, query: str, context) -> ProjectPlan``.
- Internal seam ``agents.planner._call_model(...) -> dict`` returns the raw model output.
- On schema-validation failure: retry exactly once, then raise ``PlanGenerationError``
  (safe-fail) — a malformed plan is never returned.
"""
import pytest


@pytest.mark.asyncio
async def test_valid_output_returns_projectplan(monkeypatch, valid_plan_dict):
    import agents.planner as planner
    from agents.schemas import ProjectPlan

    async def _fake(*args, **kwargs):
        return valid_plan_dict

    monkeypatch.setattr(planner, "_call_model", _fake)
    plan = await planner.generate_plan(query="launch onboarding", context=[])
    assert isinstance(plan, ProjectPlan)


@pytest.mark.asyncio
async def test_invalid_then_valid_retries_exactly_once(monkeypatch, valid_plan_dict):
    import agents.planner as planner
    from agents.schemas import ProjectPlan

    calls = {"n": 0}

    async def _fake(*args, **kwargs):
        calls["n"] += 1
        return {"bad": "output"} if calls["n"] == 1 else valid_plan_dict

    monkeypatch.setattr(planner, "_call_model", _fake)
    plan = await planner.generate_plan(query="launch onboarding", context=[])
    assert calls["n"] == 2  # one retry
    assert isinstance(plan, ProjectPlan)


@pytest.mark.asyncio
async def test_always_invalid_safe_fails_without_surfacing_a_plan(monkeypatch):
    import agents.planner as planner

    calls = {"n": 0}

    async def _fake(*args, **kwargs):
        calls["n"] += 1
        return {"bad": "output"}

    monkeypatch.setattr(planner, "_call_model", _fake)
    with pytest.raises(planner.PlanGenerationError):
        await planner.generate_plan(query="launch onboarding", context=[])
    assert calls["n"] == 2  # retried once then safe-failed, never returned a malformed plan
