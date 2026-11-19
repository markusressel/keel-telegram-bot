import sqlalchemy as sa

metadata = sa.MetaData()

# Telegram messages of approval notifications, whose buttons have to follow the state of the approval
approval_messages = sa.Table(
    "approval_messages", metadata,
    sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("message_id", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("approval_id", sa.String(255), nullable=False),
    sa.Column("identifier", sa.String(1024), nullable=False),
    # what the message currently shows, see approval_signature(). Empty for messages of unknown content.
    sa.Column("signature", sa.String(255), nullable=False, server_default=""),
    # consecutive failed edits that were not clearly permanent
    sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

# Which approval was announced in which chat, so a restart (or an approval that appeared while the bot was down)
# never leads to a missing or a duplicate notification
announced_approvals = sa.Table(
    "announced_approvals", metadata,
    sa.Column("approval_id", sa.String(255), primary_key=True),
    sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("announced_at", sa.DateTime, nullable=False),
)

# Helm chart upgrades that were started from Telegram and are still running
helm_pending_upgrades = sa.Table(
    "helm_pending_upgrades", metadata,
    sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("message_id", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("version", sa.String(255), nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

# small key/value facts about the database itself
meta = sa.Table(
    "meta", metadata,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("value", sa.String(255), nullable=False),
)
