"""Phase 23 expand: add nullable todos.completed_at alongside completed."""

import sqlalchemy as sa

from alembic import op

revision = "2026092301"
down_revision = "2026091801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "todos",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("todos", "completed_at")
