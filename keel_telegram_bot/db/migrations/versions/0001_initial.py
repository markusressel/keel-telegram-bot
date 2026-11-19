"""initial schema

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
        "approval_messages",
        sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("message_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("approval_id", sa.String(255), nullable=False),
        sa.Column("identifier", sa.String(1024), nullable=False),
        sa.Column("signature", sa.String(255), nullable=False, server_default=""),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "announced_approvals",
        sa.Column("approval_id", sa.String(255), primary_key=True),
        sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("announced_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "helm_pending_upgrades",
        sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("message_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "meta",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(255), nullable=False),
    )


def downgrade() -> None:
    for table in ("meta", "helm_pending_upgrades", "announced_approvals", "approval_messages"):
        op.drop_table(table)
