"""SQLAlchemy engine factory."""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url


def make_engine(url: str) -> Engine:
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
