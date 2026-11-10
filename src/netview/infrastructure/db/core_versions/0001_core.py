"""Core schema.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("ip", sa.String, nullable=False),
        sa.Column("mac", sa.String, nullable=True),
        sa.Column("vendor", sa.String, nullable=False, server_default=""),
        sa.Column("first_seen_ms", sa.Integer, nullable=False),
        sa.Column("last_seen_ms", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("rtt_ms", sa.Float, nullable=True),
        sa.Column("ttl", sa.Integer, nullable=True),
        sa.Column("is_self", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("missed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_new", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_devices_ip", "devices", ["ip"])
    op.create_table(
        "name_claims",
        sa.Column("key", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("rank", sa.Float, nullable=False),
        sa.Column("checked_ms", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("key", "source"),
    )
    op.create_table(
        "type_claims",
        sa.Column("key", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("reason", sa.String, nullable=False, server_default=""),
        sa.Column("updated_ms", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("key", "source"),
    )
    op.create_table(
        "hints",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("text", sa.String, nullable=False),
    )
    op.create_index("ix_hints_key", "hints", ["key"])
    op.create_table(
        "nicknames",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", sa.String, nullable=False),
    )
    op.create_table(
        "nickname_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String, nullable=False),
        sa.Column("old", sa.String, nullable=False),
        sa.Column("new", sa.String, nullable=False),
        sa.Column("by", sa.String, nullable=False),
        sa.Column("t_ms", sa.Integer, nullable=False),
    )
    op.create_index("ix_nickname_history_key", "nickname_history", ["key"])
    op.create_table(
        "watches",
        sa.Column("ip", sa.String, primary_key=True),
        sa.Column("ports", sa.String, nullable=False, server_default=""),
        sa.Column("label", sa.String, nullable=False, server_default=""),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("t_ms", sa.Integer, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("text", sa.String, nullable=False),
        sa.Column("ip", sa.String, nullable=True),
        sa.Column("key", sa.String, nullable=True),
    )
    op.create_table(
        "inspection_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ip", sa.String, nullable=False),
        sa.Column("ports_spec", sa.String, nullable=False, server_default=""),
        sa.Column("started_ms", sa.Integer, nullable=False),
        sa.Column("finished_ms", sa.Integer, nullable=False),
        sa.Column("sections_json", sa.Text, nullable=False),
    )
    op.create_index("ix_inspection_reports_ip", "inspection_reports", ["ip"])
    op.create_table(
        "plugin_state",
        sa.Column("plugin_id", sa.String, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("settings_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("installed_version", sa.String, nullable=True),
    )


def downgrade() -> None:
    for table in (
        "plugin_state",
        "inspection_reports",
        "events",
        "watches",
        "nickname_history",
        "nicknames",
        "hints",
        "type_claims",
        "name_claims",
        "devices",
    ):
        op.drop_table(table)
