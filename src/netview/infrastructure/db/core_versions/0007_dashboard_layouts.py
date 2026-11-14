"""Per-user dashboard layouts.

One row per user holding the layout as opaque JSON text; deleting the user deletes the row.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_dashboard_layouts",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("layout", sa.Text, nullable=False),
        sa.Column("updated_ms", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_dashboard_layouts")
