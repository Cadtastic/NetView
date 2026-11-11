"""Create starlink_counters: the last byte counters seen for each Wi-Fi client.

Revision ID: starlink0001
"""

import sqlalchemy as sa
from alembic import op

revision = "starlink0001"
down_revision = None
branch_labels = ("starlink",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "starlink_counters",
        sa.Column("ip", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False, server_default=""),
        sa.Column("down_bytes", sa.BigInteger, nullable=False),
        sa.Column("up_bytes", sa.BigInteger, nullable=False),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starlink_counters")
