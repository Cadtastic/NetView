"""Cache of the plugin catalog fetched from GitHub.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_catalog_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("fetched_at_ms", sa.BigInteger, nullable=True),
        sa.Column("payload", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("plugin_catalog_cache")
