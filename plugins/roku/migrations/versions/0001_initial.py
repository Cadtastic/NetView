"""Roku plugin schema: the saved TV list."""

import sqlalchemy as sa
from alembic import op

revision = "roku_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tvs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("serial", sa.String, nullable=False),
        sa.Column("ip", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("location", sa.String, nullable=False),
        sa.Column("tv", sa.Boolean, nullable=False),
        sa.Column("found_by", sa.String, nullable=False),
        sa.Column("first_seen", sa.String, nullable=False),
        sa.Column("last_seen", sa.String, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tvs")
