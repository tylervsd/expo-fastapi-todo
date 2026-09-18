"""add durable suggestion trace context

Revision ID: 2026091701
Revises: 2026091501
Create Date: 2026-09-17

Phase 21 Task 2: persist an optional canonical W3C traceparent (version 00,
at most 55 characters) alongside the existing suggestion reservation row.
Old rows read back NULL and remain executable; trace metadata never enters
fingerprints or idempotency keys.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026091701"
down_revision: str | Sequence[str] | None = "2026091501"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "todo_workflow_suggestion_requests",
        sa.Column("trace_parent", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_suggestion_requests_trace_parent",
        "todo_workflow_suggestion_requests",
        "(trace_parent IS NULL OR char_length(trace_parent) <= 55)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_suggestion_requests_trace_parent",
        "todo_workflow_suggestion_requests",
        type_="check",
    )
    op.drop_column("todo_workflow_suggestion_requests", "trace_parent")
