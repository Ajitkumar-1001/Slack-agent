"""Slack interactive-action handlers.

US2: Approve -> approve + execute + stakeholder summary.
US3: Reject / Edit Plan, plus the decision-lock "already decided" ephemeral notice
(FR-011, FR-012, FR-021). Handlers stay thin — decisions and the lock live in workflows/approve_plan.py.
"""
from typing import Any

import structlog

from agents.schemas import ProjectPlan
from db.models import ActionLogStatus
from db.session import async_session_factory
from slack.app import bolt_app
from slack.blocks import render_already_decided_notice, render_stakeholder_summary
from workflows.approve_plan import (
    DecisionLockedError,
    approve_plan,
    reject_plan,
    request_edit,
)
from workflows.create_plan import create_plan
from workflows.execute_plan import execute_plan

log = structlog.get_logger()


async def _notify_already_decided(respond: Any, exc: DecisionLockedError, attempted: str) -> None:
    """FR-021: an ignored late/duplicate action — ephemeral to the clicker, no artifact, no audit
    row. Recorded via structured logging only (per the 2026-07-05 clarification)."""
    log.info(
        "decision_ignored_already_decided",
        proposal_id=str(exc.proposal.id),
        status=exc.proposal.status.value,
        attempted=attempted,
    )
    await respond(
        text=render_already_decided_notice(status=exc.proposal.status.value),
        response_type="ephemeral",
    )


@bolt_app.action("approve_plan")
async def handle_approve(ack: Any, body: dict, action: dict, respond: Any, say: Any) -> None:
    await ack()
    proposal_id = action["value"]
    user_id = body.get("user", {}).get("id", "")

    async with async_session_factory() as session:
        # persist the approval decision (Constitution X), then perform the idempotent writes
        try:
            proposal = await approve_plan(session=session, proposal_id=proposal_id, user_id=user_id)
        except DecisionLockedError as exc:
            await _notify_already_decided(respond, exc, "approve")
            return
        outcomes = await execute_plan(session=session, proposal=proposal)
        plan = ProjectPlan(**proposal.plan_json)

    created = [
        (task.title, outcome.external_url or "")
        for task, outcome in zip(plan.tasks, outcomes)
        if outcome.status in (ActionLogStatus.SUCCEEDED, ActionLogStatus.SKIPPED_DUPLICATE)
    ]
    failed = [
        task.title
        for task, outcome in zip(plan.tasks, outcomes)
        if outcome.status == ActionLogStatus.FAILED
    ]
    open_risks = [f"{risk.title} ({risk.severity})" for risk in plan.risks]
    next_steps = (
        "Retry the failed tasks once resolved; do not re-approve — already-created issues are kept."
        if failed
        else "Track the created issues to completion."
    )

    summary = render_stakeholder_summary(
        project_name=plan.project_name,
        created=created,
        failed=failed,
        open_risks=open_risks,
        next_steps=next_steps,
    )
    await say(blocks=summary)


@bolt_app.action("reject_plan")
async def handle_reject(ack: Any, body: dict, action: dict, respond: Any) -> None:
    await ack()
    proposal_id = action["value"]
    user_id = body.get("user", {}).get("id", "")

    async with async_session_factory() as session:
        try:
            await reject_plan(session=session, proposal_id=proposal_id, user_id=user_id)
        except DecisionLockedError as exc:
            await _notify_already_decided(respond, exc, "reject")
            return

    # FR-012: nothing was created; confirm the rejection in-channel so the thread reflects the outcome
    await respond(text="Plan rejected — no issues were created.", response_type="in_channel")


@bolt_app.action("edit_plan")
async def handle_edit(ack: Any, body: dict, action: dict, respond: Any, say: Any) -> None:
    await ack()
    proposal_id = action["value"]
    user_id = body.get("user", {}).get("id", "")

    async with async_session_factory() as session:
        try:
            proposal = await request_edit(session=session, proposal_id=proposal_id, user_id=user_id)
        except DecisionLockedError as exc:
            await _notify_already_decided(respond, exc, "edit")
            return
        channel_id = proposal.slack_channel_id
        thread_ts = proposal.slack_thread_ts
        objective = proposal.objective

    # FR-011: regenerate from the thread context -> a fresh pending_approval proposal + new card.
    # ponytail: the button carries no free text, so we replan the original objective over the current
    # thread (which now holds the user's requested-changes reply). A structured edit form is post-MVP.
    event = {"text": objective, "channel": channel_id, "thread_ts": thread_ts, "user": user_id}
    await create_plan(event=event, say=say)
