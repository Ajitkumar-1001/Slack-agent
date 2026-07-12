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

    outcomes = await execute_plan(
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
