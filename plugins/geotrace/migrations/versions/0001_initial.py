"""GeoTrace schema: targets, traces and hops."""

import sqlalchemy as sa
from alembic import op

revision = "geotrace_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geotrace_target",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("address", sa.String, nullable=False),
        sa.Column("family", sa.String, nullable=False),
        sa.Column("interval_min", sa.Integer, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_ms", sa.BigInteger, nullable=False),
        sa.Column("updated_ms", sa.BigInteger, nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "geotrace_trace",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("geotrace_target.id"), nullable=True),
        sa.Column("trigger", sa.String, nullable=False),
        sa.Column("mode", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("started_ms", sa.BigInteger, nullable=False),
        sa.Column("finished_ms", sa.BigInteger, nullable=True),
        sa.Column("resolved_ip", sa.String, nullable=True),
        sa.Column("family", sa.String, nullable=False),
        sa.Column("reached", sa.Boolean, nullable=False),
        sa.Column("hop_count", sa.Integer, nullable=False),
        sa.Column("rtt_ms", sa.Float, nullable=True),
        sa.Column("loss_pct", sa.Float, nullable=True),
        sa.Column("jitter_ms", sa.Float, nullable=True),
        sa.Column("ping_min_ms", sa.Float, nullable=True),
        sa.Column("ping_max_ms", sa.Float, nullable=True),
        sa.Column("signature", sa.String, nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_geotrace_trace_target_started", "geotrace_trace", ["target_id", "started_ms"])
    op.create_table(
        "geotrace_hop",
        sa.Column("trace_id", sa.Integer, sa.ForeignKey("geotrace_trace.id"), primary_key=True),
        sa.Column("n", sa.Integer, primary_key=True),
        sa.Column("ip", sa.String, nullable=True),
        sa.Column("rtts_ms", sa.String, nullable=False),
        sa.Column("city", sa.String, nullable=False),
        sa.Column("region", sa.String, nullable=False),
        sa.Column("country", sa.String, nullable=False),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lon", sa.Float, nullable=True),
        sa.Column("asn", sa.Integer, nullable=True),
        sa.Column("as_org", sa.String, nullable=False),
        sa.Column("placement", sa.String, nullable=False),
        sa.Column("plausible", sa.Boolean, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("geotrace_hop")
    op.drop_index("ix_geotrace_trace_target_started", table_name="geotrace_trace")
    op.drop_table("geotrace_trace")
    op.drop_table("geotrace_target")
