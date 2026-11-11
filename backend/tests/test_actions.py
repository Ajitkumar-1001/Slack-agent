"""Focused tests for slack/actions.py handlers.

Covers handle_approve's post-execute summary grouping (created/failed by system, open risks,
both next_steps messages) and handle_edit's regenerate path, plus the ephemeral
NotAuthorizedError / DecisionLockedError notices that must not execute anything.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest


def _patch_session(monkeypatch):
    """Point slack.actions at a dummy session — workflows under test are patched."""
    import slack.actions as actions

    @asynccontextmanager
    async def session_factory():
        yield object()

    monkeypatch.setattr(actions, "async_session_factory", session_factory)
    return actions


async def _ack() -> None:
    pass


def _task(title: str) -> SimpleNamespace:
    return SimpleNamespace(title=title)


def _summary_text(said: list) -> str:
    assert len(said) == 1 and "blocks" in said[0]
    return json.dumps(said[0]["blocks"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_approve_summary_groups_created_failed_risks_and_retry_next_steps(
    monkeypatch, valid_plan_dict
):
    """SUCCEEDED + SKIPPED_DUPLICATE count as created (with URLs); FAILED tasks are per-system;
    open risks list every plan risk; any failure switches next_steps to the retry message."""
    from db.models import ActionLogStatus
    from tools.github import IssueOutcome

    actions = _patch_session(monkeypatch)
    proposal = SimpleNamespace(plan_json=dict(valid_plan_dict))
    executed = {"n": 0}

    async def fake_approve(*, session, proposal_id, user_id):
        return proposal

    async def fake_execute(*, session, proposal, target_systems, notion_enabled):
        executed["n"] += 1
        assert target_systems == ["github"]
        assert notion_enabled is False
        outcomes = [
            (
                _task("Build wireframes"),
                "github",
                IssueOutcome(
                    ActionLogStatus.SUCCEEDED, "1", "https://github.com/x/y/issues/1"
                ),
            ),
            (
                _task("Write copy"),
                "github",
                IssueOutcome(
                    ActionLogStatus.SKIPPED_DUPLICATE,
                    "2",
                    "https://github.com/x/y/issues/2",
                ),
            ),
            (
                _task("Set up CI"),
                "jira",
                IssueOutcome(ActionLogStatus.FAILED, None, None, "jira 500"),
            ),
        ]
        return outcomes, None

    monkeypatch.setattr(actions, "approve_plan", fake_approve)
    monkeypatch.setattr(actions, "execute_plan", fake_execute)

    said: list = []
    responded: list = []

    async def say(**kwargs):
        said.append(kwargs)

    async def respond(**kwargs):
        responded.append(kwargs)

    await actions.handle_approve(
        ack=_ack,
        body={"user": {"id": "U1"}},
        action={"value": f"{uuid4()}|github|false"},
        respond=respond,
        say=say,
    )

    assert executed["n"] == 1
    assert responded == []
    blocks = said[0]["blocks"]
    sections = [
        b["text"]["text"]
        for b in blocks
        if b.get("type") == "section" and isinstance(b.get("text"), dict)
    ]

    # Created artifacts must sit under the GitHub section, not a merged/other-system bucket.
    github_created = next(s for s in sections if s.startswith("*GitHub:* 2 issues"))
    assert "Build wireframes" in github_created
    assert "Write copy" in github_created
    assert "https://github.com/x/y/issues/1" in github_created
    assert "https://github.com/x/y/issues/2" in github_created
    assert "Set up CI" not in github_created

    # Failures are per-system; Jira's failed section must carry the exact renderer wording.
    jira_failed = next(
        s for s in sections if s.startswith("*Jira:*") and ", 1 failed" in s
    )
    assert jira_failed.startswith("*Jira:* 0 succeeded, 1 failed")
    assert "• Set up CI" in jira_failed
    assert "Build wireframes" not in jira_failed
    assert "Write copy" not in jira_failed

    text = "\n".join(sections)

    # open risks: title (severity) for every risk on the plan
    for risk in valid_plan_dict["risks"]:
        assert f"{risk['title']} ({risk['severity']})" in text

    assert (
        "Retry the failed tasks once resolved; do not re-approve — already-created issues are kept."
        in text
    )
    assert "Track the created issues to completion." not in text


@pytest.mark.asyncio
async def test_approve_summary_uses_track_message_when_nothing_failed(
    monkeypatch, valid_plan_dict
):
    from db.models import ActionLogStatus
    from tools.github import IssueOutcome

    actions = _patch_session(monkeypatch)

    async def fake_approve(*, session, proposal_id, user_id):
        return SimpleNamespace(plan_json=dict(valid_plan_dict))

    async def fake_execute(*, session, proposal, target_systems, notion_enabled):
        return [
            (
                _task("Build wireframes"),
                "github",
                IssueOutcome(
                    ActionLogStatus.SUCCEEDED, "1", "https://github.com/x/y/issues/1"
                ),
            )
        ], None

    monkeypatch.setattr(actions, "approve_plan", fake_approve)
    monkeypatch.setattr(actions, "execute_plan", fake_execute)

    said: list = []

    async def say(**kwargs):
        said.append(kwargs)

    async def respond(**kwargs):
        raise AssertionError("successful approve must not ephemeral-respond")

    await actions.handle_approve(
        ack=_ack,
        body={"user": {"id": "U1"}},
        action={"value": f"{uuid4()}|github|false"},
        respond=respond,
        say=say,
    )

    text = _summary_text(said)
    assert "https://github.com/x/y/issues/1" in text
    assert "Track the created issues to completion." in text
    assert "Retry the failed tasks" not in text


@pytest.mark.asyncio
async def test_edit_regenerates_plan_from_original_thread_context(monkeypatch):
    """FR-011: after request_edit, handle_edit re-plans the original objective in the same
    thread, keeping the original requester as the regenerated plan's owner."""
    actions = _patch_session(monkeypatch)
    captured: dict = {}

    async def fake_request_edit(*, session, proposal_id, user_id):
        return SimpleNamespace(
            slack_channel_id="C99",
            slack_thread_ts="9.9",
            objective="Ship the onboarding redesign",
            requested_by_user_id="U1",
        )

    async def fake_create_plan(*, event, say):
        captured["event"] = event
        captured["say"] = say

    monkeypatch.setattr(actions, "request_edit", fake_request_edit)
    monkeypatch.setattr(actions, "create_plan", fake_create_plan)

    async def say(**kwargs):
        pass

    async def respond(**kwargs):
        raise AssertionError("successful edit must not ephemeral-respond")

    await actions.handle_edit(
        ack=_ack,
        body={"user": {"id": "U7"}},
        action={"value": str(uuid4())},
        respond=respond,
        say=say,
    )

    assert captured["event"] == {
        "text": "Ship the onboarding redesign",
        "channel": "C99",
        "thread_ts": "9.9",
        "user": "U1",
    }
    assert captured["say"] is say


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_name,exc_kind",
    [
        ("handle_approve", "unauthorized"),
        ("handle_reject", "unauthorized"),
        ("handle_edit", "unauthorized"),
        ("handle_approve", "locked"),
        ("handle_reject", "locked"),
        ("handle_edit", "locked"),
    ],
)
async def test_auth_and_lock_errors_ephemeral_without_executing(
    monkeypatch, handler_name, exc_kind
):
    """NotAuthorizedError / DecisionLockedError: ephemeral notice only; no execute/replan."""
    from db.models import ProposalStatus
    from workflows.approve_plan import DecisionLockedError, NotAuthorizedError

    actions = _patch_session(monkeypatch)
    pid = str(uuid4())
    locked = SimpleNamespace(id=uuid4(), status=ProposalStatus.APPROVED)

    if exc_kind == "unauthorized":
        exc: Exception = NotAuthorizedError(pid, "U9")
        expected_snippet = "not allowed"
    else:
        exc = DecisionLockedError(locked)
        # Stable fragment from render_already_decided_notice (not a loose "already" match).
        expected_snippet = "the first decision wins"

    async def boom(**_kwargs):
        raise exc

    async def must_not_run(**_kwargs):
        raise AssertionError("locked/unauthorized clicks must not execute or replan")

    monkeypatch.setattr(actions, "approve_plan", boom)
    monkeypatch.setattr(actions, "reject_plan", boom)
    monkeypatch.setattr(actions, "request_edit", boom)
    monkeypatch.setattr(actions, "execute_plan", must_not_run)
    monkeypatch.setattr(actions, "create_plan", must_not_run)

    responded: list = []
    said: list = []

    async def respond(**kwargs):
        responded.append(kwargs)

    async def say(**kwargs):
        said.append(kwargs)

    value = f"{pid}|github|false" if handler_name == "handle_approve" else pid
    kwargs = {
        "ack": _ack,
        "body": {"user": {"id": "U9"}},
        "action": {"value": value},
        "respond": respond,
    }
    if handler_name != "handle_reject":
        kwargs["say"] = say

    await getattr(actions, handler_name)(**kwargs)

    assert len(responded) == 1
    assert responded[0]["response_type"] == "ephemeral"
    assert expected_snippet in responded[0]["text"]
    assert said == []
