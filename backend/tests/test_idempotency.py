"""T028 [US2] — idempotency / dedup / crash-reconciliation / partial-failure (FR-014).

RED until T031 (tools/github.py) and T033 (workflows/execute_plan.py) exist.

Interfaces imposed:
- ``compute_idempotency_key(proposal_id: str, task: Task, target_system: str) -> str`` —
  deterministic per (proposal, task, target_system); distinct target systems for the same
  task/proposal MUST NOT collide (002-flowpilot-jira-integration FR-104, research.md Decision 3).
- ``async create_issue_idempotent(*, idempotency_key, payload, find_local, search_remote,
  create_remote) -> IssueOutcome`` where the injected callables are the ONLY IO:
  ``find_local(key)`` / ``search_remote(key)`` return ``(external_id, external_url) | None``,
  ``create_remote(payload)`` returns ``(external_id, external_url)``. ``IssueOutcome`` carries
  ``.status`` (an ``ActionLogStatus``), ``.external_id``, ``.external_url``.
- ``async execute_plan(*, session, proposal, create_remote, search_remote) -> list[IssueOutcome]``
  persists one ActionLog per task; a task whose ``create_remote`` raises is recorded ``failed``
  while the others are recorded ``succeeded`` (partial success is not all-or-nothing).
"""
import pytest


async def _none(_key):
    return None


def test_idempotency_key_is_deterministic_and_task_sensitive():
    from agents.schemas import Task
    from tools.github import compute_idempotency_key

    t1 = Task(title="A", description="d", milestone=None, suggested_owner=None,
              priority="low", acceptance_criteria=[], dependencies=[])
    t2 = Task(title="B", description="d", milestone=None, suggested_owner=None,
              priority="low", acceptance_criteria=[], dependencies=[])

    assert compute_idempotency_key("prop-1", t1, "github") == compute_idempotency_key("prop-1", t1, "github")
    assert compute_idempotency_key("prop-1", t1, "github") != compute_idempotency_key("prop-1", t2, "github")
    assert compute_idempotency_key("prop-1", t1, "github") != compute_idempotency_key("prop-2", t1, "github")

    # dual-target ("Both") no-collision case (FR-104, AC-102): the same task/proposal must get a
    # distinct key per target system, since ActionLog.idempotency_key is a single-column unique
    # constraint, not composite with target_system.
    assert compute_idempotency_key("prop-1", t1, "github") != compute_idempotency_key("prop-1", t1, "jira")


@pytest.mark.asyncio
async def test_new_issue_is_created():
    from db.models import ActionLogStatus
    from tools.github import create_issue_idempotent

    created = {"n": 0}

    async def create_remote(_payload):
        created["n"] += 1
        return ("42", "https://github.com/x/y/issues/42")

    outcome = await create_issue_idempotent(
        idempotency_key="k1", payload={"title": "t"},
        find_local=_none, search_remote=_none, create_remote=create_remote,
    )
    assert outcome.status == ActionLogStatus.SUCCEEDED
    assert outcome.external_url == "https://github.com/x/y/issues/42"
    assert created["n"] == 1


@pytest.mark.asyncio
async def test_local_duplicate_is_skipped_without_creating():
    from db.models import ActionLogStatus
    from tools.github import create_issue_idempotent

    async def find_local(_key):
        return ("42", "https://github.com/x/y/issues/42")

    async def create_remote(_payload):
        raise AssertionError("must not create a duplicate when a local record exists")

    outcome = await create_issue_idempotent(
        idempotency_key="k1", payload={"title": "t"},
        find_local=find_local, search_remote=_none, create_remote=create_remote,
    )
    assert outcome.status == ActionLogStatus.SKIPPED_DUPLICATE
    assert outcome.external_id == "42"


@pytest.mark.asyncio
async def test_crash_before_persist_reconciles_via_remote_lookup():
    from db.models import ActionLogStatus
    from tools.github import create_issue_idempotent

    async def search_remote(_key):  # local record missing, but the issue exists on GitHub
        return ("99", "https://github.com/x/y/issues/99")

    async def create_remote(_payload):
        raise AssertionError("must reconcile the existing remote issue, not create a duplicate")

    outcome = await create_issue_idempotent(
        idempotency_key="k1", payload={"title": "t"},
        find_local=_none, search_remote=search_remote, create_remote=create_remote,
    )
    assert outcome.status == ActionLogStatus.SKIPPED_DUPLICATE
    assert outcome.external_id == "99"


@pytest.mark.asyncio
async def test_new_ticket_is_created():
    """T006 [US1] — mirrors test_new_issue_is_created, for tools/jira.py's create_ticket_idempotent."""
    from db.models import ActionLogStatus
    from tools.jira import create_ticket_idempotent

    created = {"n": 0}

    async def create_remote(_payload):
        created["n"] += 1
        return ("PROJ-1", "https://example.atlassian.net/browse/PROJ-1")

    outcome = await create_ticket_idempotent(
        idempotency_key="k1", payload={"fields": {"summary": "t", "labels": []}},
        find_local=_none, search_remote=_none, create_remote=create_remote,
    )
    assert outcome.status == ActionLogStatus.SUCCEEDED
    assert outcome.external_url == "https://example.atlassian.net/browse/PROJ-1"
    assert created["n"] == 1


@pytest.mark.asyncio
async def test_local_duplicate_ticket_is_skipped_without_creating():
    from db.models import ActionLogStatus
    from tools.jira import create_ticket_idempotent

    async def find_local(_key):
        return ("PROJ-1", "https://example.atlassian.net/browse/PROJ-1")

    async def create_remote(_payload):
        raise AssertionError("must not create a duplicate when a local record exists")

    outcome = await create_ticket_idempotent(
        idempotency_key="k1", payload={"fields": {"summary": "t", "labels": []}},
        find_local=find_local, search_remote=_none, create_remote=create_remote,
    )
    assert outcome.status == ActionLogStatus.SKIPPED_DUPLICATE
    assert outcome.external_id == "PROJ-1"


@pytest.mark.asyncio
async def test_crash_before_persist_reconciles_ticket_via_jql_lookup():
    from db.models import ActionLogStatus
    from tools.jira import create_ticket_idempotent

    async def search_remote(_key):  # local record missing, but the ticket exists in Jira
        return ("PROJ-9", "https://example.atlassian.net/browse/PROJ-9")

    async def create_remote(_payload):
        raise AssertionError("must reconcile the existing remote ticket, not create a duplicate")

    outcome = await create_ticket_idempotent(
        idempotency_key="k1", payload={"fields": {"summary": "t", "labels": []}},
        find_local=_none, search_remote=search_remote, create_remote=create_remote,
    )
    assert outcome.status == ActionLogStatus.SKIPPED_DUPLICATE
    assert outcome.external_id == "PROJ-9"


@pytest.mark.asyncio
async def test_both_target_retry_creates_no_duplicates(db_session, valid_plan_dict):
    """T017 [US2] — retry-safety test (AC-103; contracts/tool-adapters.md).

    Re-invoking execute_plan for the same Both-targeted proposal (simulating a retried/
    re-delivered approval outcome) must create no duplicate GitHub issue and no duplicate
    Jira ticket -- the second run's local-record lookup short-circuits both systems' writes.
    """
    from db.models import ActionLog, ExternalArtifact, ProjectProposal, ProposalStatus
    from sqlalchemy import select
    from workflows.execute_plan import execute_plan

    proposal = ProjectProposal(
        slack_channel_id="C1", slack_thread_ts="1.2", requested_by_user_id="U1",
        project_name="P", objective="O", timeline=None, status=ProposalStatus.APPROVED,
        plan_json=dict(valid_plan_dict), risk_json={},
    )
    db_session.add(proposal)
    await db_session.commit()

    github_calls = {"n": 0}
    jira_calls = {"n": 0}

    async def github_create(_payload):
        github_calls["n"] += 1
        return ("1", "https://github.com/x/y/issues/1")

    async def jira_create(_payload):
        jira_calls["n"] += 1
        return ("PROJ-1", "https://example.atlassian.net/browse/PROJ-1")

    await execute_plan(
        session=db_session, proposal=proposal, target_systems=["both"],
        create_remote=github_create, search_remote=_none,
        jira_create_remote=jira_create, jira_search_remote=_none,
    )

    # simulate a retried / re-delivered approval outcome for the same proposal
    proposal.status = ProposalStatus.APPROVED
    await db_session.commit()

    await execute_plan(
        session=db_session, proposal=proposal, target_systems=["both"],
        create_remote=github_create, search_remote=_none,
        jira_create_remote=jira_create, jira_search_remote=_none,
    )

    assert github_calls["n"] == 1
    assert jira_calls["n"] == 1

    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    assert len(rows) == 2  # one github + one jira row, never duplicated on retry

    artifacts = (await db_session.execute(select(ExternalArtifact))).scalars().all()
    assert len(artifacts) == 2


@pytest.mark.asyncio
async def test_partial_failure_persists_succeeded_and_failed_separately(db_session, valid_plan_dict):
    from db.models import ActionLog, ActionLogStatus, ProjectProposal, ProposalStatus
    from workflows.execute_plan import execute_plan

    plan = dict(valid_plan_dict)
    plan["tasks"] = [
        {"title": "Task OK", "description": "d", "milestone": None, "suggested_owner": None,
         "priority": "high", "acceptance_criteria": [], "dependencies": []},
        {"title": "Task BOOM", "description": "d", "milestone": None, "suggested_owner": None,
         "priority": "high", "acceptance_criteria": [], "dependencies": []},
    ]
    proposal = ProjectProposal(
        slack_channel_id="C1", slack_thread_ts="1.2", requested_by_user_id="U1",
        project_name="P", objective="O", timeline=None, status=ProposalStatus.APPROVED,
        plan_json=plan, risk_json={},
    )
    db_session.add(proposal)
    await db_session.commit()

    async def search_remote(_key):
        return None

    async def create_remote(payload):
        if "BOOM" in payload["title"]:
            raise RuntimeError("GitHub 500")
        return ("1", "https://github.com/x/y/issues/1")

    outcomes = await execute_plan(
        session=db_session, proposal=proposal, create_remote=create_remote, search_remote=search_remote
    )

    statuses = sorted(o.status for _, _, o in outcomes)
    assert statuses == sorted([ActionLogStatus.SUCCEEDED, ActionLogStatus.FAILED])

    from sqlalchemy import select

    rows = (await db_session.execute(select(ActionLog))).scalars().all()
    persisted = {r.status for r in rows}
    assert ActionLogStatus.SUCCEEDED in persisted and ActionLogStatus.FAILED in persisted
