"""The tile files and their SQLite index (spec 11): lookups, touches, writes and batched eviction.

Every index call opens a short-lived connection. A failing index (locked, full, overflowing numbers) reads as
a cache miss and never raises to the caller; a file that is not a database at all is deleted and recreated
(logged once), so one bad file cannot turn every tile into a 500.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")
BUSY_TIMEOUT_S = 5
EVICT_BATCH = 200
INDEX_NAME = "index.sqlite3"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS tile (source TEXT, z INT, x INT, y INT, ctype TEXT,"
    " expires_ms INT, etag TEXT, last_modified TEXT, size INT, last_used_ms INT, ext TEXT,"
    " PRIMARY KEY (source, z, x, y))"
)


@dataclass(frozen=True)
class TileRow:
    expires_ms: int
    etag: str | None
    last_modified: str | None


class TileStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._ready = False
        self._reset_lock = threading.Lock()
        self._reset_logged = False

    # -- files -----------------------------------------------------------------------------------

    def path(self, source: str, ext: str, z: int, x: int, y: int) -> Path:
        return self.folder / source / str(z) / str(x) / f"{y}.{ext}"

    def read(self, source: str, ext: str, z: int, x: int, y: int) -> bytes | None:
        try:
            return self.path(source, ext, z, x, y).read_bytes()
        except OSError:
            return None

    # -- index -----------------------------------------------------------------------------------

    def row(self, source: str, z: int, x: int, y: int) -> TileRow | None:
        def run(db: sqlite3.Connection) -> TileRow | None:
            found = db.execute(
                "SELECT expires_ms, etag, last_modified FROM tile WHERE source=? AND z=? AND x=? AND y=?",
                (source, z, x, y),
            ).fetchone()
            return None if found is None else TileRow(int(found[0]), found[1], found[2])

        return self._run(run, None)

    def touch(self, source: str, z: int, x: int, y: int, now_ms: int) -> None:
        self._run(
            lambda db: db.execute(
                "UPDATE tile SET last_used_ms=? WHERE source=? AND z=? AND x=? AND y=?",
                (now_ms, source, z, x, y),
            ),
            None,
        )

    def refresh(
        self,
        source: str,
        z: int,
        x: int,
        y: int,
        expires_ms: int,
        etag: str | None,
        modified: str | None,
        now_ms: int,
    ) -> None:
        self._run(
            lambda db: db.execute(
                "UPDATE tile SET expires_ms=?, etag=COALESCE(?, etag),"
                " last_modified=COALESCE(?, last_modified), last_used_ms=?"
                " WHERE source=? AND z=? AND x=? AND y=?",
                (expires_ms, etag, modified, now_ms, source, z, x, y),
            ),
            None,
        )

    def put(
        self,
        source: str,
        ext: str,
        coords: tuple[int, int, int],
        data: bytes,
        kind: str,
        expires_ms: int,
        etag: str | None,
        modified: str | None,
        now_ms: int,
    ) -> None:
        """Write the file (``.part``, then ``os.replace``), then its index row. Failures are logged."""
        z, x, y = coords
        path = self.path(source, ext, z, x, y)
        part = path.with_name(f"{path.name}.{threading.get_ident()}.part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(data)
            os.replace(part, path)
        except OSError:
            log.warning("GeoTrace could not write a map tile", exc_info=True)
            with contextlib.suppress(OSError):
                part.unlink()
            return
        self._run(
            lambda db: db.execute(
                "INSERT OR REPLACE INTO tile VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (source, z, x, y, kind, expires_ms, etag, modified, len(data), now_ms, ext),
            ),
            None,
        )

    def total_size(self) -> int:
        def run(db: sqlite3.Connection) -> int:
            return int(db.execute("SELECT COALESCE(SUM(size), 0) FROM tile").fetchone()[0])

        return self._run(run, 0)

    def evict(
        self, cap_bytes: int, keep_fraction: float, should_stop: Callable[[], bool] = lambda: False
    ) -> None:
        """When over ``cap_bytes``, delete least-recently-used tiles down to ``keep_fraction`` of it.

        Rows are chosen in batches of ``EVICT_BATCH``; the files are unlinked outside any transaction and the
        rows then deleted in one short one, so cache hits never wait on a long purge."""
        total = self.total_size()
        if total <= cap_bytes:
            return
        target = cap_bytes * keep_fraction
        while total > target and not should_stop():
            batch: list[tuple[str, int, int, int, str, int]] = self._run(self._oldest, [])
            chosen: list[tuple[str, int, int, int]] = []
            for source, z, x, y, ext, size in batch:
                if total <= target:
                    break
                chosen.append((source, z, x, y))
                total -= size
                with contextlib.suppress(OSError):
                    self.path(source, ext, z, x, y).unlink()
            if not chosen:
                return
            self._delete(chosen)

    def _delete(self, rows: list[tuple[str, int, int, int]]) -> None:
        def run(db: sqlite3.Connection) -> None:
            db.executemany("DELETE FROM tile WHERE source=? AND z=? AND x=? AND y=?", rows)

        self._run(run, None)

    @staticmethod
    def _oldest(db: sqlite3.Connection) -> list[tuple[str, int, int, int, str, int]]:
        rows = db.execute(
            "SELECT source, z, x, y, ext, size FROM tile ORDER BY last_used_ms LIMIT ?", (EVICT_BATCH,)
        ).fetchall()
        return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]

    # -- plumbing --------------------------------------------------------------------------------

    def _run(self, work: Callable[[sqlite3.Connection], T], default: T) -> T:
        """Run ``work`` on a fresh connection, commit and close. Any index failure gives ``default``."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.folder / INDEX_NAME, timeout=BUSY_TIMEOUT_S)
            try:
                if not self._ready:
                    conn.execute(SCHEMA)
                    self._ready = True
                result = work(conn)
                conn.commit()
                return result
            finally:
                conn.close()
        except sqlite3.OperationalError as error:
            log.debug("GeoTrace tile index busy or unavailable: %s", error)
        except sqlite3.DatabaseError as error:  # corrupt: "file is not a database", malformed image
            self._recreate(error)
        except (sqlite3.Error, OverflowError, OSError) as error:
            log.debug("GeoTrace tile index error: %s", error)
        return default

    def _recreate(self, error: Exception) -> None:
        with self._reset_lock:
            if not self._reset_logged:
                self._reset_logged = True
                log.warning("GeoTrace tile index is damaged (%s); starting a new one", error)
            self._ready = False
            for suffix in ("", "-journal", "-wal", "-shm"):
                with contextlib.suppress(OSError):
                    (self.folder / f"{INDEX_NAME}{suffix}").unlink()
