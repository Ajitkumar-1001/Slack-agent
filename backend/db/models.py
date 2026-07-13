import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


def _str_enum(enum_cls: type[Enum]) -> SAEnum:
    """Store the enum's string *values* (e.g. "proposal_created") as VARCHAR + CHECK,
    per data-model.md — not the member names, and not a native Postgres ENUM type."""
    return SAEnum(enum_cls, native_enum=False, values_callable=lambda e: [m.value for m in e])


class ProposalStatus(str, Enum):
    CREATED = "proposal_created"
    PENDING_APPROVAL = "proposal_pending_approval"
    APPROVED = "proposal_approved"
    REJECTED = "proposal_rejected"
    EDIT_REQUESTED = "proposal_edit_requested"
    EXECUTING = "proposal_executing"
    EXECUTED = "proposal_executed"
    FAILED = "proposal_failed"


class ApprovalDecisionType(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EDIT_REQUESTED = "edit_requested"


class ActionLogStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class ProjectProposal(Base):
    __tablename__ = "project_proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slack_channel_id: Mapped[str]
    slack_thread_ts: Mapped[str]
    requested_by_user_id: Mapped[str]
    project_name: Mapped[str]
    objective: Mapped[str]
    timeline: Mapped[str | None]
    status: Mapped[ProposalStatus] = mapped_column(
        _str_enum(ProposalStatus), default=ProposalStatus.CREATED
    )
    plan_json: Mapped[dict] = mapped_column(JSON)
    risk_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_proposals.id"))
    decision: Mapped[ApprovalDecisionType] = mapped_column(_str_enum(ApprovalDecisionType))
    decided_by_user_id: Mapped[str]
    decision_notes: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_proposals.id"))
    action_type: Mapped[str]
    target_system: Mapped[str]
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    request_payload_json: Mapped[dict] = mapped_column(JSON)
    response_payload_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[ActionLogStatus] = mapped_column(
        _str_enum(ActionLogStatus), default=ActionLogStatus.PROPOSED
    )
    error_message: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExternalArtifact(Base):
    __tablename__ = "external_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_proposals.id"))
    action_log_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_logs.id"))
    system: Mapped[str]
    artifact_type: Mapped[str]
    external_id: Mapped[str]
    external_url: Mapped[str]
    title: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
