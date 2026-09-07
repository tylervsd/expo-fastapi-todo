"""allow offer breakdown

Revision ID: 2026090801
Revises: 2026090702
Create Date: 2026-09-07

"""

from collections.abc import Sequence

from alembic import op

revision: str = "2026090801"
down_revision: str | Sequence[str] | None = "2026090702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE todo_workflows DROP CONSTRAINT ck_todo_workflows_state")
    op.execute(
        "ALTER TABLE todo_workflows ADD CONSTRAINT "
        "ck_todo_workflows_state CHECK (state IN "
        "('ASSESS_TASK', 'OFFER_BREAKDOWN', 'COLLECT_TASKS', "
        "'REVIEW', 'COMPLETED', 'CANCELLED'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE todo_workflows SET state = 'ASSESS_TASK', "
        "involves_multiple_steps = NULL, proposed_todo_titles = '[]'::jsonb "
        "WHERE state = 'OFFER_BREAKDOWN'"
    )
    op.execute("ALTER TABLE todo_workflows DROP CONSTRAINT ck_todo_workflows_state")
    op.execute(
        "ALTER TABLE todo_workflows ADD CONSTRAINT "
        "ck_todo_workflows_state CHECK (state IN "
        "('ASSESS_TASK', 'COLLECT_TASKS', "
        "'REVIEW', 'COMPLETED', 'CANCELLED'))"
    )
