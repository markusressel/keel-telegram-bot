from alembic import context

from keel_telegram_bot.db.tables import metadata

# the connection is handed in by keel_telegram_bot.db.Database.migrate()
connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata)

with context.begin_transaction():
    context.run_migrations()
