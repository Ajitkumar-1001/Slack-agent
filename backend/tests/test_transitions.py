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

    await approve_plan(session=db_session, proposal_id=str(proposal.id), user_id="U2")

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

    outcomes = await execute_plan(
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

    outcomes = await execute_plan(
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

    outcomes = await execute_plan(
        session=db_session, proposal=proposal, target_systems=["both"],
        create_remote=github_create, search_remote=_no_op_remote,
        jira_create_remote=jira_create_fails, jira_search_remote=_no_op_remote,
    )

    assert len(outcomes) == 2
    by_system = {system: outcome for _task, system, outcome in outcomes}
    assert by_system["github"].status == ActionLogStatus.SUCCEEDED
    assert by_system["jira"].status == ActionLogStatus.FAILED


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
async def test_approve_unknown_proposal_raises(db_session):
    from workflows.approve_plan import approve_plan

    with pytest.raises(Exception):
        await approve_plan(session=db_session, proposal_id=str(uuid.uuid4()), user_id="U2")


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

    await reject_plan(session=db_session, proposal_id=str(proposal.id), user_id="U2")

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == ProposalStatus.REJECTED

    decisions = (await db_session.execute(select(ApprovalDecision))).scalars().all()
    assert [d.decision.value for d in decisions] == ["rejected"]

    action_rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert action_rows == []  # SC-003: zero external artifacts on the reject path


@pytest.mark.asyncio
async def test_edit_supersedes_and_creates_no_artifacts(db_session, valid_plan_dict):
    """FR-011: an edit request records the decision, locks the superseded proposal
    (proposal_edit_requested), and that superseded plan can never execute -> no artifacts of its own."""
    from db.models import ActionLog, ApprovalDecision, ProposalStatus
    from sqlalchemy import select
    from workflows.approve_plan import request_edit
    from workflows.execute_plan import ExecutionNotApprovedError, execute_plan

    proposal = await _make_proposal(db_session, ProposalStatus.PENDING_APPROVAL, valid_plan_dict)

    await request_edit(session=db_session, proposal_id=str(proposal.id), user_id="U2")

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
            await action(session=db_session, proposal_id=pid, user_id="U2")
        assert excinfo.value.proposal.status == status  # notice can report the current status

    refreshed = await db_session.get(type(proposal), proposal.id)
    assert refreshed.status == status  # unchanged
    assert (await db_session.execute(select(ApprovalDecision))).scalars().all() == []
