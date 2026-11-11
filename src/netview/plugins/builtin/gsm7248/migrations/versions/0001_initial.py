"""GSM7248 plugin schema: port samples, MAC locations, snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "gsm7248_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gsm7248_port_samples",
        sa.Column("switch_id", sa.String, nullable=False),
        sa.Column("if_index", sa.Integer, nullable=False),
        sa.Column("resolution", sa.String, nullable=False),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("in_octets", sa.BigInteger, nullable=False),
        sa.Column("out_octets", sa.BigInteger, nullable=False),
        sa.Column("in_bps", sa.Float, nullable=True),
        sa.Column("out_bps", sa.Float, nullable=True),
        sa.Column("in_err_ps", sa.Float, nullable=True),
        sa.Column("out_err_ps", sa.Float, nullable=True),
        sa.Column("in_disc_ps", sa.Float, nullable=True),
        sa.Column("out_disc_ps", sa.Float, nullable=True),
        sa.Column("util_percent", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("switch_id", "if_index", "resolution", "t_ms"),
    )
    op.create_table(
        "gsm7248_mac_locations",
        sa.Column("switch_id", sa.String, nullable=False),
        sa.Column("mac", sa.String, nullable=False),
        sa.Column("vlan", sa.Integer, nullable=False),
        sa.Column("if_index", sa.Integer, nullable=False),
        sa.Column("first_ms", sa.BigInteger, nullable=False),
        sa.Column("last_ms", sa.BigInteger, nullable=False),
        sa.PrimaryKeyConstraint("switch_id", "mac", "vlan", "if_index"),
    )
    op.create_index("ix_gsm7248_mac_locations_mac", "gsm7248_mac_locations", ["switch_id", "mac"])
    op.create_table(
        "gsm7248_snapshots",
        sa.Column("switch_id", sa.String, primary_key=True),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gsm7248_snapshots")
    op.drop_index("ix_gsm7248_mac_locations_mac", table_name="gsm7248_mac_locations")
    op.drop_table("gsm7248_mac_locations")
    op.drop_table("gsm7248_port_samples")
