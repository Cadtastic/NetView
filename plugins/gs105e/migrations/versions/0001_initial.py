"""GS105E plugin schema: port samples and snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "gs105e_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_samples",
        sa.Column("switch_id", sa.String, nullable=False),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("resolution", sa.String, nullable=False),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("rx_bytes", sa.BigInteger, nullable=False),
        sa.Column("tx_bytes", sa.BigInteger, nullable=False),
        sa.Column("crc_errors", sa.BigInteger, nullable=False),
        sa.Column("in_bps", sa.Float, nullable=True),
        sa.Column("out_bps", sa.Float, nullable=True),
        sa.Column("crc_delta", sa.Integer, nullable=True),
        sa.Column("util_percent", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("switch_id", "port", "resolution", "t_ms"),
    )
    op.create_table(
        "snapshots",
        sa.Column("switch_id", sa.String, nullable=False),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("switch_id"),
    )


def downgrade() -> None:
    op.drop_table("snapshots")
    op.drop_table("port_samples")
