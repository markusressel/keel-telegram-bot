"""deferred approvals of Keel's own workload

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deferred_approvals",
        sa.Column("approval_id", sa.String(255), primary_key=True),
        sa.Column("identifier", sa.String(1024), nullable=False),
        sa.Column("voter", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(1024), nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("message_id", sa.BigInteger, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("deferred_approvals")
