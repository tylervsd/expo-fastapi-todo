"""add todo workflows

Revision ID: 2026090702
Revises: 2026090701
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2026090702"
down_revision: str | Sequence[str] | None = "2026090701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "todo_workflows",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("involves_multiple_steps", sa.Boolean(), nullable=True),
        sa.Column(
            "proposed_todo_titles",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("completion_result", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "state IN ('ASSESS_TASK', 'COLLECT_TASKS', 'REVIEW', 'COMPLETED', 'CANCELLED')",
            name="ck_todo_workflows_state",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120",
            name="ck_todo_workflows_title_length",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_todo_titles) = 'array'",
            name="ck_todo_workflows_proposals_array",
        ),
        sa.CheckConstraint(
            "completion_result IS NULL OR jsonb_typeof(completion_result) = 'object'",
            name="ck_todo_workflows_completion_object",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_todo_workflows_public_id"),
    )


def downgrade() -> None:
    op.drop_table("todo_workflows")
