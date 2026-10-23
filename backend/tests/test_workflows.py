"""T018 [US1] — create_plan acknowledgment / interim-update ordering (FR-020, SC-007).

RED until T025 creates backend/workflows/create_plan.py.

Interface imposed on T025:
- ``async create_plan(*, event: dict, say)`` where ``say`` is an async callable that posts a
  Slack message (``text=...`` for status messages, ``blocks=...`` for the approval card).
- ``create_plan`` grounds via module-level ``retrieve_context`` and generates via module-level
  ``generate_plan`` (both patchable), and MUST post an immediate ack + at least one interim
  progress update BEFORE the approval card. The 30 s wall-clock target is verified in the demo
  (quickstart Phase 7), not here.
"""
import pytest


@pytest.mark.asyncio
async def test_posts_ack_and_interim_update_before_the_card(monkeypatch, valid_plan_dict):
    import workflows.create_plan as cp
    from agents.schemas import ProjectPlan

    posted: list = []

    async def fake_say(*args, **kwargs):
        # a status message posts text=...; the approval card posts blocks=[...]
        if "blocks" in kwargs:
            posted.append(kwargs["blocks"])
        else:
            posted.append(kwargs.get("text", args[0] if args else None))

    class _Result:
        retrieval_mode = "mock"
        messages = ["some grounding context"]

    async def fake_retrieve(*args, **kwargs):
        return _Result()

    async def fake_generate(*args, **kwargs):
        return ProjectPlan(**valid_plan_dict)

    class _Proposal:
        id = "prop-xyz"

    async def fake_persist(event, plan):
        return _Proposal()

    monkeypatch.setattr(cp, "retrieve_context", fake_retrieve)
    monkeypatch.setattr(cp, "generate_plan", fake_generate)
    monkeypatch.setattr(cp, "persist_proposal", fake_persist)  # keep the unit test offline (no DB)

    await cp.create_plan(
        event={"text": "launch onboarding", "channel": "C1", "ts": "1.2"}, say=fake_say
    )

    # ack + >=1 interim update + the card => at least 3 posts
    assert len(posted) >= 3
    # the approval card (a blocks list) is the final post; everything before it is a text status message
    assert isinstance(posted[-1], list)
    assert all(isinstance(p, str) for p in posted[:-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["plan_generation", "validation", "anthropic"])
async def test_planner_failure_replies_in_thread_and_persists_nothing(
    monkeypatch, error_kind
):
    """FR-013 safe-fail: a planner failure posts a next-step reply in the request's thread,
    persists no proposal, renders no card, and logs without raw Slack text."""
    import anthropic
    import httpx
    import workflows.create_plan as cp
    from agents.planner import PlanGenerationError
    from pydantic import ValidationError
    from structlog.testing import capture_logs

    error = {
        "plan_generation": PlanGenerationError(
            "ProjectPlan validation failed after retry"
        ),
        "validation": ValidationError.from_exception_data("ProjectPlan", []),
        "anthropic": anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com")
        ),
    }[error_kind]

    posted: list = []

    async def fake_say(*args, **kwargs):
        posted.append(kwargs)

    class _Result:
        retrieval_mode = "mock"
        messages = ["some grounding context"]

    async def fake_retrieve(*args, **kwargs):
        return _Result()

    async def failing_generate(*args, **kwargs):
        raise error

    async def fake_persist(event, plan):
        raise AssertionError("no proposal may be persisted when planning fails")

    monkeypatch.setattr(cp, "retrieve_context", fake_retrieve)
    monkeypatch.setattr(cp, "generate_plan", failing_generate)
    monkeypatch.setattr(cp, "persist_proposal", fake_persist)

    request_text = "launch the confidential onboarding revamp"
    with capture_logs() as logs:
        await cp.create_plan(
            event={"text": request_text, "channel": "C1", "ts": "1.2"}, say=fake_say
        )

    assert not any("blocks" in p for p in posted)  # no approval card
    assert "try again" in posted[-1]["text"] and "rephrase" in posted[-1]["text"]
    assert posted[-1]["thread_ts"] == "1.2"

    failures = [e for e in logs if e["event"] == "plan_generation_failed"]
    assert failures and failures[0]["error_type"] == type(error).__name__
    assert request_text not in repr(logs)


@pytest.mark.asyncio
async def test_unrelated_planner_exception_still_propagates(monkeypatch):
    """FR-013 handling is scoped to planner/LLM errors — anything else must not be swallowed."""
    import workflows.create_plan as cp

    class _Result:
        retrieval_mode = "mock"
        messages = ["context"]

    async def fake_retrieve(*args, **kwargs):
        return _Result()

    async def broken_generate(*args, **kwargs):
        raise RuntimeError("bug")

    async def fake_say(*args, **kwargs):
        pass

    monkeypatch.setattr(cp, "retrieve_context", fake_retrieve)
    monkeypatch.setattr(cp, "generate_plan", broken_generate)

    with pytest.raises(RuntimeError):
        await cp.create_plan(event={"text": "x", "channel": "C1", "ts": "1.2"}, say=fake_say)


@pytest.mark.asyncio
async def test_both_target_creates_one_github_issue_and_one_jira_ticket_per_task(
    db_session, valid_plan_dict
):
    """T016 [US2] — dual-target artifact test (AC-102; contracts/tool-adapters.md).

    Approving a plan with target Both must produce exactly one GitHub issue and one Jira
    ticket per approved task -- not a shared or collapsed write across systems.
    """
    from db.models import ExternalArtifact, ProjectProposal, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    proposal = ProjectProposal(
        slack_channel_id="C1", slack_thread_ts="1.2", requested_by_user_id="U1",
        project_name="P", objective="O", timeline=None, status=ProposalStatus.APPROVED,
        plan_json=dict(valid_plan_dict), risk_json={},
    )
    db_session.add(proposal)
    await db_session.commit()

    async def no_op(_key):
        return None

    async def github_create(_payload):
        return ("1", "https://github.com/x/y/issues/1")

    async def jira_create(_payload):
        return ("PROJ-1", "https://example.atlassian.net/browse/PROJ-1")

    outcomes, _notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, target_systems=["both"],
        create_remote=github_create, search_remote=no_op,
        jira_create_remote=jira_create, jira_search_remote=no_op,
    )

    assert len(outcomes) == 2  # one task x two systems
    assert sorted(system for _task, system, _outcome in outcomes) == ["github", "jira"]

    artifacts = (await db_session.execute(select(ExternalArtifact))).scalars().all()
    assert sorted(a.system for a in artifacts) == ["github", "jira"]
    assert next(a for a in artifacts if a.system == "github").artifact_type == "issue"
    assert next(a for a in artifacts if a.system == "jira").artifact_type == "ticket"


@pytest.mark.asyncio
async def test_drive_enabled_configured_merges_tagged_context(monkeypatch, valid_plan_dict):
    """T006 [US1] — context-merge tagging (FR-303; contracts/tool-adapters.md).

    RED until T011 extends create_plan.py's Context Retrieval step.

    Interface imposed on T011: create_plan.py imports the Drive adapter as
    ``import tools.google_drive as google_drive`` (qualified, not ``from ... import retrieve_context``,
    which would collide with Slack RTS's own ``retrieve_context`` name already imported there) and,
    when ``settings.default_google_drive_enabled and settings.google_drive_credentials``, merges
    ``[slack] ...``-tagged Slack messages with ``[drive] ...``-tagged Drive documents (Slack entries
    first) into the single ``context`` list passed to ``generate_plan``.
    """
    import workflows.create_plan as cp
    from agents.schemas import ProjectPlan
    from app.config import settings

    monkeypatch.setattr(settings, "default_google_drive_enabled", True)
    monkeypatch.setattr(settings, "google_drive_credentials", '{"fake": "creds"}')

    class _SlackResult:
        retrieval_mode = "mock"
        messages = ["slack context here"]

    class _DriveResult:
        retrieval_mode = "drive"
        documents = ["drive context here"]

    captured_context = {}

    async def fake_slack_retrieve(*args, **kwargs):
        return _SlackResult()

    async def fake_drive_retrieve(*args, **kwargs):
        return _DriveResult()

    async def fake_generate(*, query, context):
        captured_context["value"] = context
        return ProjectPlan(**valid_plan_dict)

    class _Proposal:
        id = "prop-xyz"

    async def fake_persist(event, plan):
        return _Proposal()

    async def fake_say(*args, **kwargs):
        pass

    monkeypatch.setattr(cp, "retrieve_context", fake_slack_retrieve)
    monkeypatch.setattr(cp.google_drive, "retrieve_context", fake_drive_retrieve)
    monkeypatch.setattr(cp, "generate_plan", fake_generate)
    monkeypatch.setattr(cp, "persist_proposal", fake_persist)

    await cp.create_plan(
        event={"text": "onboarding", "channel": "C1", "ts": "1.2"}, say=fake_say
    )

    assert captured_context["value"] == ["[slack] slack context here", "[drive] drive context here"]


@pytest.mark.asyncio
async def test_drive_disabled_or_unconfigured_never_calls_adapter(monkeypatch, valid_plan_dict):
    """T012 [US2] — config-gate zero-calls (AC-302; research.md Decision 5).

    Covers both halves of the gate: disabled outright, and enabled but uncredentialed.
    google_drive.retrieve_context must never be invoked in either case — not called-and-
    short-circuited, actually never invoked.
    """
    import workflows.create_plan as cp
    from agents.schemas import ProjectPlan
    from app.config import settings

    class _SlackResult:
        retrieval_mode = "mock"
        messages = ["slack only"]

    calls = {"n": 0}

    async def fake_slack_retrieve(*args, **kwargs):
        return _SlackResult()

    async def fake_drive_retrieve(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("google_drive.retrieve_context must not be called")

    async def fake_generate(*, query, context):
        return ProjectPlan(**valid_plan_dict)

    class _Proposal:
        id = "prop-xyz"

    async def fake_persist(event, plan):
        return _Proposal()

    async def fake_say(*args, **kwargs):
        pass

    monkeypatch.setattr(cp, "retrieve_context", fake_slack_retrieve)
    monkeypatch.setattr(cp.google_drive, "retrieve_context", fake_drive_retrieve)
    monkeypatch.setattr(cp, "generate_plan", fake_generate)
    monkeypatch.setattr(cp, "persist_proposal", fake_persist)

    # Case 1: disabled outright
    monkeypatch.setattr(settings, "default_google_drive_enabled", False)
    monkeypatch.setattr(settings, "google_drive_credentials", None)
    await cp.create_plan(event={"text": "x", "channel": "C1", "ts": "1.2"}, say=fake_say)
    assert calls["n"] == 0

    # Case 2: enabled but no credentials configured
    monkeypatch.setattr(settings, "default_google_drive_enabled", True)
    monkeypatch.setattr(settings, "google_drive_credentials", None)
    await cp.create_plan(event={"text": "x", "channel": "C1", "ts": "1.2"}, say=fake_say)
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_drive_enabled_but_adapter_fails_create_plan_still_completes(
    monkeypatch, valid_plan_dict
):
    """T014 [US2] — end-to-end resilience (AC-303).

    Uses the REAL google_drive.retrieve_context (left un-mocked) so its own internal
    try/except containment (T009) is genuinely exercised through create_plan end-to-end —
    only the lower-level _get_access_token seam is forced to fail. This deliberately does NOT
    mock google_drive.retrieve_context itself away, since research.md Decision 5 puts failure
    containment inside the adapter, not create_plan.py — a test that bypassed the real adapter
    and made the mock raise directly would test a scenario T009's own contract rules out.
    """
    import tools.google_drive as gd
    import workflows.create_plan as cp
    from agents.schemas import ProjectPlan
    from app.config import settings

    monkeypatch.setattr(settings, "default_google_drive_enabled", True)
    monkeypatch.setattr(settings, "google_drive_credentials", '{"fake": "creds"}')

    async def failing_token():
        raise RuntimeError("simulated hard Drive failure")

    monkeypatch.setattr(gd, "_get_access_token", failing_token)

    class _SlackResult:
        retrieval_mode = "mock"
        messages = ["slack only"]

    posted: list = []

    async def fake_say(*args, **kwargs):
        if "blocks" in kwargs:
            posted.append(kwargs["blocks"])
        else:
            posted.append(kwargs.get("text", args[0] if args else None))

    async def fake_slack_retrieve(*args, **kwargs):
        return _SlackResult()

    async def fake_generate(*, query, context):
        return ProjectPlan(**valid_plan_dict)

    class _Proposal:
        id = "prop-xyz"

    async def fake_persist(event, plan):
        return _Proposal()

    monkeypatch.setattr(cp, "retrieve_context", fake_slack_retrieve)
    monkeypatch.setattr(cp, "generate_plan", fake_generate)
    monkeypatch.setattr(cp, "persist_proposal", fake_persist)

    await cp.create_plan(event={"text": "x", "channel": "C1", "ts": "1.2"}, say=fake_say)

    assert isinstance(posted[-1], list)  # the approval card still rendered despite the Drive failure
