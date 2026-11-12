"""SQLAlchemy engine factories."""

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url


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


def plugin_data_file(data_dir: Path, guid: str) -> Path:
    """Where a plugin keeps its own tables: ``<data dir>/plugin-data/<guid>.db``."""
    return data_dir / "plugin-data" / f"{guid}.db"


def _deny_attach(action: int, *_rest: Any) -> int:
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def make_plugin_engine(path: Path) -> Engine:
    """A dedicated engine (and pool) for one plugin's own database file.

    The file holds only that plugin's tables, so the one thing denied is reaching another database file:
    ATTACH and DETACH. Everything else is allowed.
    """
    engine = make_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _fence(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.set_authorizer(_deny_attach)

    return engine
