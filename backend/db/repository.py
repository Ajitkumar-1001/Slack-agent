import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ActionLog, ApprovalDecision, ExternalArtifact, ProjectProposal


class ProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, proposal: ProjectProposal) -> ProjectProposal:
        self.session.add(proposal)
        await self.session.flush()
        return proposal

    async def get(self, proposal_id: uuid.UUID) -> ProjectProposal | None:
        return await self.session.get(ProjectProposal, proposal_id)


class ApprovalDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, decision: ApprovalDecision) -> ApprovalDecision:
        self.session.add(decision)
        await self.session.flush()
        return decision


class ActionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, action_log: ActionLog) -> ActionLog:
        self.session.add(action_log)
        await self.session.flush()
        return action_log

    async def get_by_idempotency_key(self, idempotency_key: str) -> ActionLog | None:
        result = await self.session.execute(
            select(ActionLog).where(ActionLog.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()


class ExternalArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, artifact: ExternalArtifact) -> ExternalArtifact:
        self.session.add(artifact)
        await self.session.flush()
        return artifact
