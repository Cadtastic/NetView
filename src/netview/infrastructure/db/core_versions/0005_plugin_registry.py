"""Plugin registry: a database-assigned source_id per plugin guid, and pending uninstalls.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_registry",
        sa.Column("source_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guid", sa.String, nullable=False, unique=True),
        sa.Column("last_folder", sa.String, nullable=True),
        sqlite_autoincrement=True,  # a deleted max id is never reused
    )
    op.create_table(
        "plugin_uninstall_pending",
        sa.Column("folder", sa.String, primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("plugin_uninstall_pending")
    op.drop_table("plugin_registry")
