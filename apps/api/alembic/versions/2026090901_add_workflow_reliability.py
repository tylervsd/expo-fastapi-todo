"""add workflow reliability

Revision ID: 2026090901
Revises: 2026090801
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2026090901"
down_revision: str | Sequence[str] | None = "2026090801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_WORKFLOW_REVISION = 2147483647


def upgrade() -> None:
    op.add_column("todo_workflows", sa.Column("revision", sa.Integer(), nullable=True))
    op.add_column(
        "todo_workflows", sa.Column("definition_version", sa.Integer(), nullable=True)
    )
    op.execute(
        "UPDATE todo_workflows SET revision = 0, definition_version = 1 "
        "WHERE revision IS NULL OR definition_version IS NULL"
    )
    op.alter_column(
        "todo_workflows", "revision", existing_type=sa.Integer(), nullable=False,
        server_default="0",
    )
    op.alter_column(
        "todo_workflows",
        "definition_version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )
    op.create_check_constraint(
        "ck_todo_workflows_revision_range",
        "todo_workflows",
        f"revision BETWEEN 0 AND {MAX_WORKFLOW_REVISION}",
    )
    op.create_check_constraint(
        "ck_todo_workflows_definition_version",
        "todo_workflows",
        "definition_version >= 1",
    )
    op.create_unique_constraint(
        "uq_todo_workflows_public_owner",
        "todo_workflows",
        ["public_id", "owner_id"],
    )
    op.create_table(
        "todo_workflow_start_requests",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_snapshot", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_start_requests_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(accepted_snapshot) = 'object'",
            name="ck_start_requests_snapshot_object",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["todo_workflows.public_id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint(
            "owner_id", "request_id", name="pk_todo_workflow_start_requests"
        ),
    )
    op.create_table(
        "todo_workflow_action_requests",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("accepted_snapshot", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_action_requests_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(accepted_snapshot) = 'object'",
            name="ck_action_requests_snapshot_object",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "owner_id"],
            ["todo_workflows.public_id", "todo_workflows.owner_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "owner_id",
            "workflow_id",
            "request_id",
            name="pk_todo_workflow_action_requests",
        ),
    )


def downgrade() -> None:
    op.drop_table("todo_workflow_action_requests")
    op.drop_table("todo_workflow_start_requests")
    op.drop_constraint(
        "uq_todo_workflows_public_owner", "todo_workflows", type_="unique"
    )
    op.drop_constraint(
        "ck_todo_workflows_definition_version", "todo_workflows", type_="check"
    )
    op.drop_constraint(
        "ck_todo_workflows_revision_range", "todo_workflows", type_="check"
    )
    op.alter_column(
        "todo_workflows",
        "definition_version",
        existing_type=sa.Integer(),
        server_default=None,
    )
    op.alter_column(
        "todo_workflows", "revision", existing_type=sa.Integer(), server_default=None
    )
    op.drop_column("todo_workflows", "definition_version")
    op.drop_column("todo_workflows", "revision")
