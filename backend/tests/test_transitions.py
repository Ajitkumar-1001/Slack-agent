"""T029 [US2] — approval-state transition tests (FR-010; Constitution X).

RED until T032 (workflows/approve_plan.py) and T033 (workflows/execute_plan.py) exist.

Interfaces imposed:
- ``async approve_plan(*, session, proposal_id, user_id) -> ProjectProposal`` — records an
  ``ApprovalDecision(approved)`` and transitions ``pending_approval -> approved`` (the decision
  is persisted before any external write happens in execute_plan).
- ``async execute_plan(*, session, proposal, create_remote, search_remote)`` — transitions
  ``executing -> executed``, and MUST refuse to run (no write) unless the proposal is approved.
"""
import uuid

import pytest


async def _no_op_remote(_arg):
    return None


async def _ok_create(_payload):
    return ("1", "https://github.com/x/y/issues/1")


async def _make_proposal(session, status, valid_plan_dict):
    from db.models import ProjectProposal

    proposal = ProjectProposal(
        slack_channel_id="C1", slack_thread_ts="1.2", requested_by_user_id="U1",
        project_name="P", objective="O", timeline=None, status=status,
        plan_json=dict(valid_plan_dict), risk_json={},
    )
    session.add(proposal)
    await session.commit()
    return proposal


@pytest.mark.asyncio
async def test_approve_records_decision_and_transitions_to_approved(db_session, valid_plan_dict):
    from db.models import ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import approve_plan

    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict)

    await approve_plan(session=db_session, proposal_id=str(proposal.id), user_id="U1")

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.APPROVED

    decisions = (await db_session.execute(select(ApprovalDecision))).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].decision.value == "approved"


@pytest.mark.asyncio
async def test_jira_only_target_creates_zero_github_issues(db_session, valid_plan_dict):
    """T008 [US1] — Jira-only execution routing (AC-101; contracts/tool-adapters.md).

    RED until T013 extends workflows/execute_plan.py with target_systems dispatch: a new
    ``target_systems: list[str] | None = None`` param plus ``jira_create_remote``/
    ``jira_search_remote`` injected callables alongside the existing GitHub ones, returning
    ``list[tuple[Task, target_system, IssueOutcome]]`` instead of one outcome per task.
    """
    from db.models import ProposalStatus
    from workflows.execute_plan import execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, valid_plan_dict)
    assert len(dict(valid_plan_dict)["tasks"]) == 1  # fixture has exactly one task

    github_calls = {"n": 0}

    async def github_create(_payload):
        github_calls["n"] += 1
        return ("1", "https://github.com/x/y/issues/1")

    async def jira_create(_payload):
        return ("PROJ-1", "https://example.atlassian.net/browse/PROJ-1")

    outcomes, _notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, target_systems=["jira"],
        create_remote=github_create, search_remote=_no_op_remote,
        jira_create_remote=jira_create, jira_search_remote=_no_op_remote,
    )

    assert github_calls["n"] == 0
    assert len(outcomes) == 1
    _task, target_system, outcome = outcomes[0]
    assert target_system == "jira"
    assert outcome.status.value == "succeeded"
    assert outcome.external_url == "https://example.atlassian.net/browse/PROJ-1"


@pytest.mark.asyncio
async def test_both_target_produces_ten_action_log_rows_for_five_tasks(db_session, valid_plan_dict):
    """T015 [US2] — dual-target ActionLog test (FR-103, AC-102; contracts/tool-adapters.md).

    Approving a 5-task plan with target Both must produce 10 ActionLog rows (5 github, 5 jira),
    each with a distinct idempotency_key -- the idempotency-key fix (T003) folding target_system
    into the hash is what makes this possible without a unique-constraint collision.
    """
    from db.models import ActionLog, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    plan = dict(valid_plan_dict)
    plan["tasks"] = [
        {"title": f"Task {i}", "description": "d", "milestone": None, "suggested_owner": None,
         "priority": "medium", "acceptance_criteria": [], "dependencies": []}
        for i in range(5)
    ]
    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, plan)

    github_ids = iter(range(1, 100))
    jira_ids = iter(range(1, 100))

    async def github_create(_payload):
        n = next(github_ids)
        return (str(n), f"https://github.com/x/y/issues/{n}")

    async def jira_create(_payload):
        n = next(jira_ids)
        return (f"PROJ-{n}", f"https://example.atlassian.net/browse/PROJ-{n}")

    outcomes, _notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, target_systems=["both"],
        create_remote=github_create, search_remote=_no_op_remote,
        jira_create_remote=jira_create, jira_search_remote=_no_op_remote,
    )
    assert len(outcomes) == 10

    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert len(rows) == 10
    assert sorted(r.target_system for r in rows) == ["github"] * 5 + ["jira"] * 5
    assert len({r.idempotency_key for r in rows}) == 10  # all distinct, no collisions


@pytest.mark.asyncio
async def test_both_target_isolates_per_system_failure(db_session, valid_plan_dict):
    """T018 [US2] — cross-system failure isolation (AC-102/FR-017; contracts/tool-adapters.md).

    When Jira fails for a task but GitHub succeeds for it under Both, both outcomes are recorded
    independently -- neither system's write blocks the other, nor aborts the remaining tasks.
    """
    from db.models import ActionLogStatus, ProposalStatus
    from workflows.execute_plan import execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, valid_plan_dict)

    async def github_create(_payload):
        return ("1", "https://github.com/x/y/issues/1")

    async def jira_create_fails(_payload):
        raise RuntimeError("Jira 500")

    outcomes, _notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, target_systems=["both"],
        create_remote=github_create, search_remote=_no_op_remote,
        jira_create_remote=jira_create_fails, jira_search_remote=_no_op_remote,
    )

    assert len(outcomes) == 2
    by_system = {system: outcome for _task, system, outcome in outcomes}
    assert by_system["github"].status == ActionLogStatus.SUCCEEDED
    assert by_system["jira"].status == ActionLogStatus.FAILED


@pytest.mark.asyncio
async def test_notion_enabled_execution_adds_one_action_log_and_artifact_and_returns_notion_outcome(
    db_session, valid_plan_dict
):
    """T006 [US1] — Notion execution-wiring test (contracts/tool-adapters.md).

    RED until T012 extends execute_plan with notion_enabled and a proposal-scoped Notion call
    made once after the existing per-task GitHub/Jira loop.
    """
    from db.models import ActionLog, ExternalArtifact, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, valid_plan_dict)

    async def notion_create(_payload):
        return ("notion-page-1", "https://notion.so/notion-page-1")

    async def notion_search(_key):
        return None

    outcomes, notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, create_remote=_ok_create, search_remote=_no_op_remote,
        notion_enabled=True, notion_create_remote=notion_create, notion_search_remote=notion_search,
    )

    assert len(outcomes) == 1  # per-task GitHub outcome list is unchanged in shape
    assert notion_outcome is not None
    assert notion_outcome.status.value == "succeeded"
    assert notion_outcome.external_url == "https://notion.so/notion-page-1"

    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    notion_rows = [r for r in rows if r.target_system == "notion"]
    assert len(notion_rows) == 1

    artifacts = (await db_session.execute(select(ExternalArtifact))).scalars().all()
    notion_artifacts = [a for a in artifacts if a.system == "notion"]
    assert len(notion_artifacts) == 1


@pytest.mark.asyncio
async def test_notion_remote_reconciliation_through_execute_plan(db_session, valid_plan_dict):
    """T016 [US2] — remote-reconciliation-through-execution test (contracts/tool-adapters.md).

    Complements T004's adapter-level coverage by driving the same reconciliation case through
    execute_plan's actual wiring: no local ActionLog record exists for the Notion key, but the
    injected notion_search_remote reports an already-tagged page -- execute_plan's Notion call
    must reconcile (SKIPPED_DUPLICATE) instead of creating a duplicate page.
    """
    from db.models import ActionLog, ActionLogStatus, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, valid_plan_dict)

    async def notion_search(_key):  # local record missing, but the page already exists in Notion
        return ("page-9", "https://notion.so/page-9")

    async def notion_create(_payload):
        raise AssertionError("must reconcile the existing remote page, not create a duplicate")

    outcomes, notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, create_remote=_ok_create, search_remote=_no_op_remote,
        notion_enabled=True, notion_create_remote=notion_create, notion_search_remote=notion_search,
    )

    assert len(outcomes) == 1
    assert notion_outcome is not None
    assert notion_outcome.status == ActionLogStatus.SKIPPED_DUPLICATE
    assert notion_outcome.external_id == "page-9"

    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    notion_rows = [r for r in rows if r.target_system == "notion"]
    assert len(notion_rows) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("target_systems", [None, ["github"], ["jira"], ["both"]])
async def test_notion_disabled_execution_never_calls_notion_adapter(
    db_session, valid_plan_dict, target_systems
):
    """T019 [US3] — toggle-off zero-write test (contracts/tool-adapters.md).

    With notion_enabled left at its default (False), execute_plan must never call the Notion
    adapter -- regardless of target_systems -- and must return notion_outcome=None. The injected
    notion_create_remote/notion_search_remote raise if called at all, proving they're unreached.
    """
    from db.models import ProposalStatus
    from workflows.execute_plan import execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, valid_plan_dict)

    async def notion_create(_payload):
        raise AssertionError("must not call the Notion adapter when notion_enabled is False")

    async def notion_search(_key):
        raise AssertionError("must not call the Notion adapter when notion_enabled is False")

    async def jira_create(_payload):
        return ("PROJ-1", "https://example.atlassian.net/browse/PROJ-1")

    _outcomes, notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, target_systems=target_systems,
        create_remote=_ok_create, search_remote=_no_op_remote,
        jira_create_remote=jira_create, jira_search_remote=_no_op_remote,
        notion_create_remote=notion_create, notion_search_remote=notion_search,
    )

    assert notion_outcome is None


@pytest.mark.asyncio
async def test_execute_transitions_to_executed(db_session, valid_plan_dict):
    from db.models import ProposalStatus
    from workflows.execute_plan import execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, valid_plan_dict)
    await execute_plan(
        session=db_session, proposal=proposal, create_remote=_ok_create, search_remote=_no_op_remote
    )
    assert proposal.status == ProposalStatus.EXECUTED


@pytest.mark.asyncio
async def test_execution_requires_approval(db_session, valid_plan_dict):
    from db.models import ActionLog, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    # a proposal that was never approved must not be executable
    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict)
    with pytest.raises(Exception):
        await execute_plan(
            session=db_session, proposal=proposal, create_remote=_ok_create, search_remote=_no_op_remote
        )
    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert rows == []  # zero external writes attempted


@pytest.mark.asyncio
async def test_create_plan_with_drive_creates_zero_actionlog_or_artifact_rows(
    monkeypatch, db_session, valid_plan_dict
):
    """T016 [US3] — zero-persistence (AC-304).

    Runs create_plan for real (not persist_proposal-mocked) against the test's in-memory DB,
    with Drive enabled and returning content, and confirms Drive retrieval itself writes no
    ActionLog/ExternalArtifact row — it has no write path of any kind (FR-305). Also confirms
    the persisted plan_json contains no raw Drive file content beyond whatever evidence_summary
    the (mocked, fixture-returning) planner itself produced.
    """
    import json

    import workflows.create_plan as cp
    from agents.schemas import ProjectPlan
    from app.config import settings
    from db.models import ActionLog, ExternalArtifact, ProjectProposal
    from sqlalchemy import select

    monkeypatch.setattr(settings, "default_google_drive_enabled", True)
    monkeypatch.setattr(settings, "google_drive_credentials", '{"fake": "creds"}')

    class _SingleSessionFactory:
        """Adapts a single already-open test session to async_session_factory()'s
        `async with factory() as session` call shape, so create_plan.persist_proposal's real
        code path runs against the in-memory db_session fixture instead of the real (unreachable
        in tests) Postgres async_session_factory."""

        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(cp, "async_session_factory", _SingleSessionFactory(db_session))

    class _SlackResult:
        retrieval_mode = "mock"
        messages = ["slack context"]

    class _DriveResult:
        retrieval_mode = "drive"
        documents = ["drive doc content that must never be persisted verbatim"]

    async def fake_slack_retrieve(*args, **kwargs):
        return _SlackResult()

    async def fake_drive_retrieve(*args, **kwargs):
        return _DriveResult()

    async def fake_generate(*, query, context):
        return ProjectPlan(**valid_plan_dict)

    async def fake_say(*args, **kwargs):
        pass

    monkeypatch.setattr(cp, "retrieve_context", fake_slack_retrieve)
    monkeypatch.setattr(cp.google_drive, "retrieve_context", fake_drive_retrieve)
    monkeypatch.setattr(cp, "generate_plan", fake_generate)

    await cp.create_plan(event={"text": "x", "channel": "C1", "ts": "1.2"}, say=fake_say)

    action_rows = (await db_session.execute(select(ActionLog))).scalars().all()
    artifact_rows = (await db_session.execute(select(ExternalArtifact))).scalars().all()
    assert action_rows == []
    assert artifact_rows == []

    proposals = (await db_session.execute(select(ProjectProposal))).scalars().all()
    assert len(proposals) == 1
    assert "drive doc content" not in json.dumps(proposals[0].plan_json)


@pytest.mark.asyncio
async def test_execute_plan_identical_regardless_of_drive_tagged_evidence_summary(
    db_session, valid_plan_dict
):
    """T017 [US3] — non-interference regression (AC-305), execution + audit-log side.

    execute_plan never reads evidence_summary — a Drive-grounded proposal's ActionLog rows and
    outcomes must match test_execute_transitions_to_executed's Slack-only equivalent exactly.
    """
    from db.models import ActionLog, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    drive_grounded_plan = dict(valid_plan_dict)
    drive_grounded_plan["evidence_summary"] = [
        "[slack] Thread references a Q3 launch commitment",
        "[drive] Project charter excerpt",
    ]

    proposal = await _make_proposal(db_session, ProposalStatus.APPROVED, drive_grounded_plan)

    outcomes, notion_outcome = await execute_plan(
        session=db_session, proposal=proposal, create_remote=_ok_create, search_remote=_no_op_remote
    )

    assert len(outcomes) == 1
    _task, target_system, outcome = outcomes[0]
    assert target_system == "github"
    assert outcome.status.value == "succeeded"
    assert notion_outcome is None
    assert proposal.status == ProposalStatus.EXECUTED

    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].target_system == "github"


@pytest.mark.asyncio
async def test_reject_identical_regardless_of_drive_tagged_evidence_summary(db_session, valid_plan_dict):
    """T017 [US3] — non-interference regression (AC-305), reject path."""
    from db.models import ActionLog, ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import reject_plan

    drive_grounded_plan = dict(valid_plan_dict)
    drive_grounded_plan["evidence_summary"] = [
        "[slack] Thread references a Q3 launch commitment",
        "[drive] Project charter excerpt",
    ]

    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, drive_grounded_plan)

    await reject_plan(session=db_session, proposal_id=str(proposal.id), user_id="U1")

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.REJECTED

    decisions = (await db_session.execute(select(ApprovalDecision))).scalars().all()
    assert [d.decision.value for d in decisions] == ["rejected"]

    action_rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert action_rows == []  # identical to the Slack-only reject guarantee


@pytest.mark.asyncio
async def test_approve_unknown_proposal_raises(db_session):
    from workflows.approve_plan import approve_plan

    with pytest.raises(Exception):
        await approve_plan(session=db_session, proposal_id=str(uuid.uuid4()), user_id="U1")


# ---------------------------------------------------------------------------
# T036 [US3] — reject, edit, and decision-lock transitions (FR-011, FR-012, FR-021).
#   RED until T037/T038/T039 add reject_plan, request_edit, and claim_pending_proposal
#   (the shared decision-lock guard) to workflows/approve_plan.py.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_records_decision_and_creates_no_artifacts(db_session, valid_plan_dict):
    """FR-012: reject transitions to proposal_rejected, records the rejection, writes nothing external."""
    from db.models import ActionLog, ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import reject_plan

    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict)

    await reject_plan(session=db_session, proposal_id=str(proposal.id), user_id="U1")

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.REJECTED

    decisions = (await db_session.execute(select(ApprovalDecision))).scalars().all()
    assert [d.decision.value for d in decisions] == ["rejected"]

    action_rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert action_rows == []  # SC-003: zero external artifacts on the reject path


@pytest.mark.asyncio
async def test_reject_creates_no_notion_artifacts_even_if_toggle_was_enabled(db_session, valid_plan_dict):
    """T020 [US3] — rejected-plan zero-Notion-writes test (AC-205; contracts/tool-adapters.md).

    The Notion toggle is a transient value carried only in the Approve button's own value
    (data-model.md) -- it never reaches reject_plan, and reject_plan never calls execute_plan, so
    a proposal rejected while its card's toggle was checked produces zero Notion ActionLog/
    ExternalArtifact rows, exactly like the existing GitHub/Jira zero-artifact reject guarantee.
    """
    from db.models import ActionLog, ExternalArtifact, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import reject_plan

    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict)

    await reject_plan(session=db_session, proposal_id=str(proposal.id), user_id="U1")

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.REJECTED

    action_rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert [r for r in action_rows if r.target_system == "notion"] == []

    artifact_rows = (await db_session.execute(select(ExternalArtifact))).scalars().all()
    assert [a for a in artifact_rows if a.system == "notion"] == []


@pytest.mark.asyncio
async def test_edit_supersedes_and_creates_no_artifacts(db_session, valid_plan_dict):
    """FR-011: an edit request records the decision, locks the superseded proposal
    (proposal_edit_requested), and that superseded plan can never execute -> no artifacts of its own."""
    from db.models import ActionLog, ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import request_edit
    from workflows.execute_plan import ExecutionNotApprovedError, execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict)

    await request_edit(session=db_session, proposal_id=str(proposal.id), user_id="U1")

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.EDIT_REQUESTED

    decisions = (await db_session.execute(select(ApprovalDecision))).scalars().all()
    assert [d.decision.value for d in decisions] == ["edit_requested"]

    # the superseded proposal is not approved, so execution refuses it and writes nothing
    # (the regenerated plan is a separate pending_approval proposal produced by create_plan)
    with pytest.raises(ExecutionNotApprovedError):
        await execute_plan(
            session=db_session, proposal=refreshed, create_remote=_ok_create, search_remote=_no_op_remote
        )
    assert (await db_session.execute(select(ActionLog))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("locked_status", ["APPROVED", "EXECUTING", "EXECUTED", "REJECTED"])
async def test_decision_lock_ignores_later_actions(db_session, valid_plan_dict, locked_status):
    """FR-021: once a proposal has left pending_approval, further Approve/Edit/Reject are ignored
    (DecisionLockedError), change no state, and record no new decision — the first decision wins.
    Covers the mid-execution case (locked_status=EXECUTING), i.e. no edit while executing (CHK010)."""
    from db.models import ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import (
        DecisionLockedError,
        approve_plan,
        reject_plan,
        request_edit,
    )

    status = getattr(ProposalStatus, locked_status)
    proposal = await _make_proposal(db_session, status, valid_plan_dict)
    pid = str(proposal.id)

    for action in (approve_plan, reject_plan, request_edit):
        with pytest.raises(DecisionLockedError) as excinfo:
            await action(session=db_session, proposal_id=pid, user_id="U1")
        assert excinfo.value.proposal.status == status  # notice can report the current status

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == status  # unchanged
    assert (await db_session.execute(select(ApprovalDecision))).scalars().all() == []


# ---------------------------------------------------------------------------
# Approver authorization: only the requester or an allowlisted approver may decide.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", ["U9", ""])
async def test_non_requester_cannot_decide_and_nothing_changes(
    monkeypatch, db_session, valid_plan_dict, user_id
):
    from app.config import Settings, settings
    from db.models import ActionLog, ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import (
        NotAuthorizedError,
        approve_plan,
        reject_plan,
        request_edit,
    )

    # requester-only unless FLOWPILOT_APPROVER_IDS is set
    assert Settings.model_fields["flowpilot_approver_ids"].default == ""
    monkeypatch.setattr(settings, "flowpilot_approver_ids", "")
    proposal = await _make_proposal(
        db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict
    )
    pid = str(proposal.id)

    for action in (approve_plan, reject_plan, request_edit):
        with pytest.raises(NotAuthorizedError):
            await action(session=db_session, proposal_id=pid, user_id=user_id)

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.PENDING_APPROVAL
    assert (await db_session.execute(select(ApprovalDecision))).scalars().all() == []
    assert (await db_session.execute(select(ActionLog))).scalars().all() == []


@pytest.mark.asyncio
async def test_allowlisted_approver_can_decide(monkeypatch, db_session, valid_plan_dict):
    from app.config import settings
    from db.models import ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import approve_plan

    monkeypatch.setattr(settings, "flowpilot_approver_ids", " U7 , U8,")
    proposal = await _make_proposal(
        db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict
    )

    await approve_plan(session=db_session, proposal_id=str(proposal.id), user_id="U8")

    assert proposal.status == ProposalStatus.APPROVED
    decisions = (await db_session.execute(select(ApprovalDecision))).scalars().all()
    assert [d.decided_by_user_id for d in decisions] == ["U8"]


def _patch_action_session(monkeypatch, db_session):
    """Point slack.actions at the in-memory test session, not the real Postgres one."""
    from contextlib import asynccontextmanager

    import slack.actions as actions

    @asynccontextmanager
    async def session_factory():
        yield db_session

    monkeypatch.setattr(actions, "async_session_factory", session_factory)
    return actions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_name", ["handle_approve", "handle_reject", "handle_edit"]
)
async def test_unauthorized_click_gets_ephemeral_refusal_and_writes_nothing(
    monkeypatch, db_session, valid_plan_dict, handler_name
):
    from app.config import settings
    from db.models import ActionLog, ApprovalDecision, ExternalArtifact, ProposalStatus
    from sqlalchemy import select
    from structlog.testing import capture_logs

    monkeypatch.setattr(settings, "flowpilot_approver_ids", "")
    actions = _patch_action_session(monkeypatch, db_session)

    async def must_not_run(**_kwargs):
        raise AssertionError("an unauthorized click must not execute or replan")

    monkeypatch.setattr(actions, "execute_plan", must_not_run)
    monkeypatch.setattr(actions, "create_plan", must_not_run)

    proposal = await _make_proposal(
        db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict
    )
    pid = str(proposal.id)
    value = f"{pid}|github|false" if handler_name == "handle_approve" else pid
    responded: list = []
    said: list = []

    async def ack():
        pass

    async def respond(**kwargs):
        responded.append(kwargs)

    async def say(**kwargs):
        said.append(kwargs)

    kwargs = {
        "ack": ack,
        "body": {"user": {"id": "U9"}},
        "action": {"value": value},
        "respond": respond,
    }
    if handler_name != "handle_reject":
        kwargs["say"] = say

    with capture_logs() as logs:
        await getattr(actions, handler_name)(**kwargs)

    assert len(responded) == 1
    assert responded[0]["response_type"] == "ephemeral"
    assert "not allowed" in responded[0]["text"]
    assert said == []

    audit = [e for e in logs if e["event"] == "decision_unauthorized"]
    assert audit and audit[0]["user_id"] == "U9" and audit[0]["proposal_id"] == pid

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.PENDING_APPROVAL
    for model in (ApprovalDecision, ActionLog, ExternalArtifact):
        assert (await db_session.execute(select(model))).scalars().all() == []


@pytest.mark.asyncio
async def test_edit_by_approver_keeps_original_requester_on_regenerated_plan(
    monkeypatch, db_session, valid_plan_dict
):
    from app.config import settings
    from db.models import ProposalStatus

    monkeypatch.setattr(settings, "flowpilot_approver_ids", "U7")
    actions = _patch_action_session(monkeypatch, db_session)
    captured: dict = {}

    async def fake_create_plan(*, event, say):
        captured["event"] = event

    monkeypatch.setattr(actions, "create_plan", fake_create_plan)

    proposal = await _make_proposal(
        db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict
    )

    async def noop(**_kwargs):
        pass

    async def ack():
        pass

    await actions.handle_edit(
        ack=ack,
        body={"user": {"id": "U7"}},
        action={"value": str(proposal.id)},
        respond=noop,
        say=noop,
    )

    assert proposal.status == ProposalStatus.EDIT_REQUESTED
    assert captured["event"]["user"] == "U1"  # not the approver who clicked Edit
