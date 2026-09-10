"""add recoverable workflow suggestions

Revision ID: 2026091001
Revises: 2026090901
Create Date: 2026-09-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2026091001"
down_revision: str | Sequence[str] | None = "2026090901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_WORKFLOW_REVISION = 2147483647


def upgrade() -> None:
    op.create_table(
        "todo_workflow_suggestion_requests",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "proposed_titles",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_suggestion_requests_fingerprint_hex",
        ),
        sa.CheckConstraint(
            f"base_revision BETWEEN 0 AND {MAX_WORKFLOW_REVISION}",
            name="ck_suggestion_requests_revision_range",
        ),
        sa.CheckConstraint(
            "char_length(step_id) >= 1",
            name="ck_suggestion_requests_step_id",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'superseded')",
            name="ck_suggestion_requests_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_titles) = 'array'",
            name="ck_suggestion_requests_titles_array",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('not_configured', 'timeout', 'provider_unavailable', 'invalid_output')",
            name="ck_suggestion_requests_error_code",
        ),
        sa.CheckConstraint(
            "(" 
            "status = 'ready' AND error_code IS NULL AND "
            "CASE WHEN jsonb_typeof(proposed_titles) = 'array' "
            "THEN jsonb_array_length(proposed_titles) ELSE -1 END BETWEEN 2 AND 10"
            ") OR ("
            "status = 'failed' AND error_code IS NOT NULL AND "
            "proposed_titles = '[]'::jsonb"
            ") OR ("
            "status IN ('pending', 'superseded') AND error_code IS NULL AND "
            "proposed_titles = '[]'::jsonb"
            ")",
            name="ck_suggestion_requests_status_fields",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "owner_id"],
            ["todo_workflows.public_id", "todo_workflows.owner_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "workflow_id",
            "request_id",
            name="uq_suggestion_requests_owner_workflow_request",
        ),
    )
    op.create_index(
        "ix_suggestion_requests_owner_workflow_id",
        "todo_workflow_suggestion_requests",
        ["owner_id", "workflow_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_suggestion_requests_owner_workflow_id",
        table_name="todo_workflow_suggestion_requests",
    )
    op.drop_table("todo_workflow_suggestion_requests")
