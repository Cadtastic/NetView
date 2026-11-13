"""A copy of ``netview.db`` taken before the migration that re-keys plugins by guid."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

REVISION = "0006"
"""The core revision that does the re-key; the backup is made while the database is below it."""


def backup_path(db_path: Path, today: date) -> Path:
    return db_path.with_name(f"{db_path.name}.bak-{today.isoformat()}-before-plugin-identity")


_UNREADABLE = object()
"""``_revision`` could not open the file to ask; the backup is then taken anyway."""


def _readonly_uri(posix_path: str) -> str:
    """A read-only SQLite URI for an absolute path written with forward slashes.

    '#', '?' and '%' are percent-encoded. A UNC path (``//host/share/x.db``) needs an empty authority,
    so it becomes ``file:////host/share/x.db``; a drive path becomes ``file:C:/dir/x.db``.
    """
    prefix = "file://" if posix_path.startswith("//") else "file:"
    return prefix + quote(posix_path, safe="/:") + "?mode=ro"


def _revision(db_path: Path) -> object:
    """The core revision, ``None`` when there is none (a database the migrations never touched), or
    ``_UNREADABLE`` when the file could not be opened to find out."""
    uri = _readonly_uri(Path(os.path.abspath(db_path)).as_posix())
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        log.warning("cannot open %s to read its revision: %s", db_path, exc)
        return _UNREADABLE
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error as exc:
        if "no such table" in str(exc):
            return None  # no version table: a database the migrations have not touched
        log.warning("cannot read the revision of %s: %s", db_path, exc)
        return _UNREADABLE
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
    if revision is not _UNREADABLE and (revision is None or str(revision) >= REVISION):
        return None
    # fail closed: when the revision cannot be read, back up anyway rather than risk migrating without one
    target = backup_path(db_path, today)
    if target.exists():
        return None
    part = target.with_name(target.name + ".part")  # the backup only gets its name once it is complete
    part.unlink(missing_ok=True)  # left by a process that was killed mid-backup
    source = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(part))
    try:
        source.backup(dest)
    except BaseException:
        dest.close()
        source.close()
        part.unlink(missing_ok=True)
        raise
    dest.close()
    source.close()
    try:
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    log.info("backed up %s to %s", db_path, target)
    return target
