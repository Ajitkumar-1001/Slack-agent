"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROPOSAL_STATUS = [
    "proposal_created",
    "proposal_pending_approval",
    "proposal_approved",
    "proposal_rejected",
    "proposal_edit_requested",
    "proposal_executing",
    "proposal_executed",
    "proposal_failed",
]
APPROVAL_DECISION = ["approved", "rejected", "edit_requested"]
ACTION_LOG_STATUS = [
    "proposed",
    "approved",
    "executing",
    "succeeded",
    "failed",
    "skipped_duplicate",
]


def upgrade() -> None:
    op.create_table(
        "project_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slack_channel_id", sa.String(), nullable=False),
        sa.Column("slack_thread_ts", sa.String(), nullable=False),
        sa.Column("requested_by_user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("timeline", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*PROPOSAL_STATUS, name="proposalstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("risk_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("project_proposals.id"), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(*APPROVAL_DECISION, name="approvaldecisiontype", native_enum=False),
            nullable=False,
        ),
        sa.Column("decided_by_user_id", sa.String(), nullable=False),
        sa.Column("decision_notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "action_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("project_proposals.id"), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("target_system", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_payload_json", sa.JSON(), nullable=False),
        sa.Column("response_payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*ACTION_LOG_STATUS, name="actionlogstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_action_logs_idempotency_key"),
    )
    op.create_table(
        "external_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("project_proposals.id"), nullable=False),
        sa.Column("action_log_id", sa.Uuid(), sa.ForeignKey("action_logs.id"), nullable=False),
        sa.Column("system", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("external_url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("external_artifacts")
    op.drop_table("action_logs")
    op.drop_table("approval_decisions")
    op.drop_table("project_proposals")
