"""Local accounts, roles, sessions and auth settings.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String, nullable=False, unique=True),
        sa.Column("display_name", sa.String, nullable=False, server_default=""),
        sa.Column("email", sa.String, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("builtin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String, nullable=False, server_default="local"),
        sa.Column("created_ms", sa.BigInteger, nullable=False),
        sa.Column("last_sign_in_ms", sa.BigInteger, nullable=True),
    )
    op.create_index(
        "uq_users_one_builtin",
        "users",
        ["builtin"],
        unique=True,
        sqlite_where=sa.text("builtin = 1"),
        postgresql_where=sa.text("builtin = 1"),
    )
    op.create_table(
        "user_logins",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String, primary_key=True),
        sa.Column("subject", sa.String, primary_key=True),
        sa.Column("password_hash", sa.String, nullable=True),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("builtin", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.String, primary_key=True),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.String, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_ms", sa.BigInteger, nullable=False),
        sa.Column("last_seen_ms", sa.BigInteger, nullable=False),
        sa.Column("ip", sa.String, nullable=False, server_default=""),
        sa.Column("user_agent", sa.String, nullable=False, server_default=""),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.bulk_insert(
        roles,
        [
            {"id": "administrator", "name": "Administrator", "builtin": True},
            {"id": "default", "name": "Default", "builtin": True},
        ],
    )
    op.bulk_insert(role_permissions, [{"role_id": "default", "permission_id": "core.view"}])


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("user_logins")
    op.drop_index("uq_users_one_builtin", table_name="users")
    op.drop_table("users")
