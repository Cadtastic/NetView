"""Alembic environment: runs on a connection supplied by ``migrate.py``; no autogenerate."""

from alembic import context

config = context.config
connection = config.attributes["connection"]
version_table = config.attributes.get("version_table", "alembic_version")

context.configure(connection=connection, target_metadata=None, version_table=version_table)
with context.begin_transaction():
    context.run_migrations()
