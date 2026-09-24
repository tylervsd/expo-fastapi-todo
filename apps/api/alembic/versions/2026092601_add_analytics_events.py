"""Phase 26: transactional analytics event outbox (no free-text columns)."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "2026092601"
down_revision = "2026092301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("user_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "schema_version", sa.SmallInteger(), server_default="1", nullable=False
        ),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_analytics_events_event_id"),
        sa.CheckConstraint(
            "event_name IN ('user_signed_up', 'workflow_started', "
            "'workflow_completed', 'suggestion_finished')",
            name="ck_analytics_events_name",
        ),
        sa.CheckConstraint(
            "(event_name = 'suggestion_finished') = "
            "(outcome IS NOT NULL AND outcome IN ('ready', 'failed', 'expired'))",
            name="ck_analytics_events_outcome",
        ),
    )
    op.create_index(
        "ix_analytics_events_unexported",
        "analytics_events",
        ["id"],
        postgresql_where=sa.text("exported_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_events_unexported", table_name="analytics_events")
    op.drop_table("analytics_events")
