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


def test_build_user_message_renders_mixed_source_context_under_one_header():
    """T007 [US1] — tagged-context rendering (FR-303; contracts/context-retrieval.md).

    RED until T010 renames agents/prompts.py's context-block header from
    "Retrieved Slack context:" to "Retrieved context:".
    """
    from agents.prompts import build_user_message

    msg = build_user_message(
        "launch onboarding", ["[slack] thread says Q3", "[drive] spec doc excerpt"]
    )

    assert "Retrieved context:" in msg
    assert "- [slack] thread says Q3" in msg
    assert "- [drive] spec doc excerpt" in msg


def test_build_user_message_empty_context_still_renders_none_available():
    """T007 [US1] — empty-context wording updates but behavior doesn't regress."""
    from agents.prompts import build_user_message

    msg = build_user_message("launch onboarding", [])

    assert "Retrieved context: (none available)" in msg


def test_system_prompt_instructs_preserving_source_tag_in_evidence_summary():
    """T008 [US1] — SYSTEM_PROMPT source-tag-preservation instruction (FR-303; research.md Decision 3).

    RED until T010 adds this rule to SYSTEM_PROMPT. This only checks the instruction text exists —
    it cannot assert real-model compliance, which every _call_model-mocking test in this file is
    structurally unable to exercise; that's covered only by quickstart.md's manual end-to-end demo.
    """
    from agents.prompts import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "evidence_summary" in lowered
    assert "preserve" in lowered
    assert "[slack]" in lowered or "[drive]" in lowered or "[source]" in lowered
