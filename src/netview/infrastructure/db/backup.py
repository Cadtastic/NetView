"""A copy of ``netview.db`` taken before the migration that re-keys plugins by guid."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

REVISION = "0006"
"""The core revision that does the re-key; the backup is made while the database is below it."""


def backup_path(db_path: Path, today: date) -> Path:
    return db_path.with_name(f"{db_path.name}.bak-{today.isoformat()}-before-plugin-identity")


def _revision(db_path: Path) -> str | None:
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None  # no version table: a database the migrations have not touched
    finally:
        con.close()
    return str(row[0]) if row else None


def backup_before_plugin_identity(db_path: Path, today: date) -> Path | None:
    """Back up ``db_path`` when it exists and is below revision 0006. ``None`` when nothing was done.

    SQLite's backup API is used because the database is in WAL mode, where a plain file copy can miss data.
    An existing backup is never overwritten.
    """
    if not db_path.is_file():
        return None
    revision = _revision(db_path)
    if revision is None or revision >= REVISION:
        return None
    target = backup_path(db_path, today)
    if target.exists():
        return None
    source = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(target))
    try:
        source.backup(dest)
    except BaseException:
        dest.close()
        target.unlink(missing_ok=True)
        raise
    finally:
        dest.close()
        source.close()
    log.info("backed up %s to %s", db_path, target)
    return target
