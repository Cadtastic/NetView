import sqlalchemy as sa
from alembic import op

revision = "good0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("items", sa.Column("id", sa.Integer, primary_key=True))


def downgrade() -> None:
    op.drop_table("items")
