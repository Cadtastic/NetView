"""SQLAlchemy engine factories."""

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url

_WRITE_ACTIONS = frozenset({sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE})


def make_engine(url: URL | str) -> Engine:
    """Create an engine; for SQLite, create the parent folder and set WAL + foreign keys on connect."""
    parsed = make_url(url)
    is_sqlite = parsed.get_backend_name() == "sqlite"
    if is_sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            # pysqlite's own transaction handling starts a transaction lazily, at the first write;
            # take over, as SQLAlchemy documents, so a transaction starts when the session begins.
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin(conn: Any) -> None:
            # IMMEDIATE, not a plain BEGIN: a read-then-write unit of work that began on an older
            # snapshot cannot upgrade to a writer in WAL mode ("database is locked"), so writers queue
            # on SQLite's busy timeout instead.
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def plugin_write_fence(plugin_id: str) -> Any:
    """A sqlite3 authorizer that denies INSERT/UPDATE/DELETE on tables the plugin does not own.

    Allowed: tables named ``<plugin_id>_*``, ``alembic_version_<plugin_id>`` and SQLite's own
    ``sqlite_*`` tables. Reads, and every other kind of statement, are not restricted.
    """
    prefix = f"{plugin_id}_"
    version_table = f"alembic_version_{plugin_id}"

    def authorizer(action: int, table: str | None, *_rest: Any) -> int:
        if action in _WRITE_ACTIONS:
            name = table or ""
            if not (name.startswith(prefix) or name == version_table or name.startswith("sqlite_")):
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return authorizer


def make_plugin_engine(url: URL | str, plugin_id: str) -> Engine:
    """A dedicated engine (and pool) for one plugin, whose connections carry the write fence.

    The core engine's connections are never touched. Needs a file database: an in-memory SQLite
    database is private to its connection, so a second engine would see a different database.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        raise ValueError("plugin write fencing is only implemented for SQLite")
    if not parsed.database or parsed.database == ":memory:":
        raise ValueError("plugin write fencing needs a file database")
    engine = make_engine(parsed)
    authorizer = plugin_write_fence(plugin_id)

    @event.listens_for(engine, "connect")
    def _fence(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.set_authorizer(authorizer)

    return engine
