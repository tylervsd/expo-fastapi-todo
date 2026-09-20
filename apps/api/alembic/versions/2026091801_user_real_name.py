"""Add optional encrypted real name; existing accounts remain NULL."""

import sqlalchemy as sa

from alembic import op

revision = "2026091801"
down_revision = "2026091701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("real_name_ciphertext", sa.LargeBinary(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "real_name_ciphertext")
