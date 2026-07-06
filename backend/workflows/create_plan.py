"""Create-plan workflow: request -> ack + progress -> RTS context -> plan -> persist -> card.

No external writes here (US1): the only persistence is the proposal itself (pending approval).
"""
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from agents.planner import generate_plan
from agents.schemas import ProjectPlan
from db.models import ProjectProposal, ProposalStatus
from db.repository import ProposalRepository
from db.session import async_session_factory
from slack.blocks import render_approval_card
from tools.slack_rts import retrieve_context

log = structlog.get_logger()

# ponytail: default to the ADR-005 event-payload fallback until live RTS is wired
# (tools.slack_rts._rts_search); swap to "rts" once a workspace with RTS is available.
_DEFAULT_RETRIEVAL_MODE = "event_payload"

Say = Callable[..., Awaitable[Any]]


async def persist_proposal(event: dict, plan: ProjectPlan) -> ProjectProposal:
    async with async_session_factory() as session:
        proposal = ProjectProposal(
            slack_channel_id=event.get("channel", ""),
            slack_thread_ts=event.get("thread_ts") or event.get("ts", ""),
            requested_by_user_id=event.get("user", ""),
            project_name=plan.project_name,
            objective=plan.objective,
            timeline=plan.timeline,
            status=ProposalStatus.PENDING_APPROVAL,
            plan_json=plan.model_dump(),
            risk_json={"risks": [r.model_dump() for r in plan.risks]},
        )
        await ProposalRepository(session).add(proposal)
        await session.commit()
        return proposal


async def create_plan(*, event: dict, say: Say) -> None:
    await say(text="Got it — I'll turn this into an execution plan and check relevant Slack context first.")

    query = event.get("text", "")

    await say(text="Searching relevant Slack context…")
    context = await retrieve_context(query=query, event=event, mode=_DEFAULT_RETRIEVAL_MODE)

    await say(text="Drafting execution plan…")
    plan = await generate_plan(query=query, context=context.messages)

    proposal = await persist_proposal(event, plan)
    log.info("proposal_created", proposal_id=str(proposal.id), retrieval_mode=context.retrieval_mode)

    card = render_approval_card(
        proposal_id=str(proposal.id),
        plan=plan,
        action_summary=f"Create {len(plan.tasks)} GitHub issue(s)",
    )
    await say(blocks=card)
