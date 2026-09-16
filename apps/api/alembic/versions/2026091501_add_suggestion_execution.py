"""add suggestion execution metadata

Revision ID: 2026091501
Revises: 2026091001
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2026091501"
down_revision: str | Sequence[str] | None = "2026091001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "todo_workflow_suggestion_requests",
        sa.Column(
            "queued_at", postgresql.TIMESTAMP(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "todo_workflow_suggestion_requests",
        sa.Column(
            "expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "todo_workflow_suggestion_requests",
        sa.Column(
            "provider_started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "todo_workflow_suggestion_requests",
        sa.Column("goal_snapshot", sa.Text(), nullable=True),
    )
    op.add_column(
        "todo_workflow_suggestion_requests",
        sa.Column("clarification_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_suggestion_requests_execution_coherent",
        "todo_workflow_suggestion_requests",
        "(queued_at IS NULL AND expires_at IS NULL "
        "AND provider_started_at IS NULL AND goal_snapshot IS NULL "
        "AND clarification_snapshot IS NULL) "
        "OR (queued_at IS NOT NULL AND expires_at IS NOT NULL "
        "AND goal_snapshot IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_suggestion_requests_expiry_order",
        "todo_workflow_suggestion_requests",
        "(expires_at IS NULL OR queued_at IS NULL OR expires_at > queued_at)",
    )
    op.create_check_constraint(
        "ck_suggestion_requests_claim_order",
        "todo_workflow_suggestion_requests",
        "(provider_started_at IS NULL OR queued_at IS NULL "
        "OR provider_started_at >= queued_at)",
    )
    op.create_check_constraint(
        "ck_suggestion_requests_goal_snapshot",
        "todo_workflow_suggestion_requests",
        "(goal_snapshot IS NULL "
        "OR char_length(goal_snapshot) BETWEEN 1 AND 120)",
    )
    op.create_check_constraint(
        "ck_suggestion_requests_clarification_object",
        "todo_workflow_suggestion_requests",
        "(clarification_snapshot IS NULL "
        "OR jsonb_typeof(clarification_snapshot) = 'object')",
    )
    op.create_index(
        "ix_suggestion_requests_pending_cloud_expiry",
        "todo_workflow_suggestion_requests",
        ["expires_at", "id"],
        postgresql_where=sa.text(
            "status = 'pending' AND queued_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_suggestion_requests_pending_cloud_expiry",
        table_name="todo_workflow_suggestion_requests",
    )
    op.drop_constraint(
        "ck_suggestion_requests_clarification_object",
        "todo_workflow_suggestion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_suggestion_requests_goal_snapshot",
        "todo_workflow_suggestion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_suggestion_requests_claim_order",
        "todo_workflow_suggestion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_suggestion_requests_expiry_order",
        "todo_workflow_suggestion_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_suggestion_requests_execution_coherent",
        "todo_workflow_suggestion_requests",
        type_="check",
    )
    op.drop_column("todo_workflow_suggestion_requests", "clarification_snapshot")
    op.drop_column("todo_workflow_suggestion_requests", "goal_snapshot")
    op.drop_column("todo_workflow_suggestion_requests", "provider_started_at")
    op.drop_column("todo_workflow_suggestion_requests", "expires_at")
    op.drop_column("todo_workflow_suggestion_requests", "queued_at")
