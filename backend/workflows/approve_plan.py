"""Approve / reject / edit decision handling + the shared decision-lock guard.

Constitution X; ADR-004; FR-010 (approve), FR-011 (edit), FR-012 (reject), FR-021 (decision-lock).

Every decision is durably recorded before any external write. Once a proposal leaves
pending_approval, ``claim_pending_proposal`` makes every further Approve/Edit/Reject a no-op
(``DecisionLockedError``) — the first decision wins (FR-021). An ignored action creates no
external artifact and no new audit row; the Slack layer surfaces an ephemeral "already decided"
notice and logs it (structured logging only).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApprovalDecision, ApprovalDecisionType, ProjectProposal, ProposalStatus
from db.repository import ApprovalDecisionRepository


class ProposalNotFoundError(Exception):
    pass


class DecisionLockedError(Exception):
    """A decision arrived for a proposal that is no longer pending approval — it is ignored (FR-021).

    Carries the current proposal so the caller can surface an "already decided" notice with its status."""

    def __init__(self, proposal: ProjectProposal) -> None:
        self.proposal = proposal
        super().__init__(f"proposal {proposal.id} already decided (status={proposal.status.value})")


async def claim_pending_proposal(*, session: AsyncSession, proposal_id: str) -> ProjectProposal:
    """Atomically claim a still-pending proposal for a decision — the shared decision-lock guard (T039).

    Locks the row (``FOR UPDATE`` where the backend supports it; a no-op on SQLite, which serializes
    writes anyway) so two near-simultaneous clicks resolve first-writer-wins. Raises
    ``DecisionLockedError`` if the proposal has already left ``pending_approval`` — the later
    Approve/Edit/Reject is ignored, including while the proposal is executing (FR-021)."""
    proposal = await session.get(ProjectProposal, uuid.UUID(proposal_id), with_for_update=True)
    if proposal is None:
        raise ProposalNotFoundError(proposal_id)
    if proposal.status != ProposalStatus.PENDING_APPROVAL:
        raise DecisionLockedError(proposal)
    return proposal


async def _record_decision(
    *,
    session: AsyncSession,
    proposal: ProjectProposal,
    decision: ApprovalDecisionType,
    new_status: ProposalStatus,
    user_id: str,
    notes: str | None = None,
) -> ProjectProposal:
    """Persist the ApprovalDecision, transition the proposal, and commit. Shared by all three
    decisions so the decision is always durably recorded before the caller does anything else."""
    await ApprovalDecisionRepository(session).add(
        ApprovalDecision(
            proposal_id=proposal.id,
            decision=decision,
            decided_by_user_id=user_id,
            decision_notes=notes,
        )
    )
    proposal.status = new_status
    await session.commit()
    return proposal


async def approve_plan(*, session: AsyncSession, proposal_id: str, user_id: str) -> ProjectProposal:
    """FR-010: record an ApprovalDecision(approved) before any external write, then transition to
    approved. execute_plan performs the writes only after this decision is persisted."""
    proposal = await claim_pending_proposal(session=session, proposal_id=proposal_id)
    return await _record_decision(
        session=session,
        proposal=proposal,
        decision=ApprovalDecisionType.APPROVED,
        new_status=ProposalStatus.APPROVED,
        user_id=user_id,
    )


async def reject_plan(*, session: AsyncSession, proposal_id: str, user_id: str) -> ProjectProposal:
    """FR-012: record the rejection, transition to proposal_rejected, create zero external artifacts."""
    proposal = await claim_pending_proposal(session=session, proposal_id=proposal_id)
    return await _record_decision(
        session=session,
        proposal=proposal,
        decision=ApprovalDecisionType.REJECTED,
        new_status=ProposalStatus.REJECTED,
        user_id=user_id,
    )


async def request_edit(
    *, session: AsyncSession, proposal_id: str, user_id: str, edit_notes: str | None = None
) -> ProjectProposal:
    """FR-011: record the edit request and lock the superseded proposal (proposal_edit_requested).

    The regenerated plan is produced as a fresh pending_approval proposal by create_plan; this one
    is now terminal for execution and creates no external artifacts of its own."""
    proposal = await claim_pending_proposal(session=session, proposal_id=proposal_id)
    return await _record_decision(
        session=session,
        proposal=proposal,
        decision=ApprovalDecisionType.EDIT_REQUESTED,
        new_status=ProposalStatus.EDIT_REQUESTED,
        user_id=user_id,
        notes=edit_notes,
    )
