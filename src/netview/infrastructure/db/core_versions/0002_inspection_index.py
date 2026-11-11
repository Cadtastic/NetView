"""Index inspection reports by (ip, id), so the latest report of a device is an index seek.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_inspection_reports_ip_id", "inspection_reports", ["ip", "id"])


def downgrade() -> None:
    op.drop_index("ix_inspection_reports_ip_id", table_name="inspection_reports")
