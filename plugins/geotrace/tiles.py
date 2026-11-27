"""Map tiles fetched by the server and kept on disk (spec 11).

NetView's CSP only lets the browser load images from NetView itself, so every tile comes through here.
Tiles are never prefetched. Files live at ``<folder>/<source>/<z>/<x>/<y>.<ext>``; ``index.sqlite3`` in the
same folder holds what is needed to decide freshness, revalidate and evict least-recently-used tiles.
"""

from __future__ import annotations

import contextlib
import http.client
import logging
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .settings import GeoTraceSettings

log = logging.getLogger(__name__)

USER_AGENT = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
MAX_TILE_BYTES = 1_048_576
TIMEOUT_S = 8.0
PER_SOURCE_LIMIT = 2
EVICT_TO = 0.9
DAY_S = 86_400
TOKENS = ("{z}", "{x}", "{y}")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

Opener = Callable[..., Any]
_warned: set[str] = set()


@dataclass(frozen=True)
class TileSource:
    name: str
    url: str
    max_zoom: int
    min_fresh_s: int
    ext: str
    credit: str


_OSM = TileSource(
    "osm",
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    19,
    7 * DAY_S,
    "png",
    "© OpenStreetMap contributors",
)
_EOX = TileSource(
    "eox-s2",
    "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg",
    14,
    DAY_S,
    "jpg",
    "Sentinel-2 cloudless 2020 by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2020)",
)


def _valid_template(url: str) -> bool:
    if not url.startswith("https://") or any(token not in url for token in TOKENS):
        return False
    host = urllib.parse.urlsplit(url).hostname or ""
    return bool(host) and "{" not in host and "}" not in host


def sources(settings: GeoTraceSettings) -> dict[str, TileSource]:
    found = {_OSM.name: _OSM, _EOX.name: _EOX}
    if settings.tile_source == "custom":
        url = settings.custom_tile_url
        if _valid_template(url):
            ext = "jpg" if url.lower().endswith((".jpg", ".jpeg")) else "png"
            found["custom"] = TileSource("custom", url, 19, DAY_S, ext, "Custom tile server")
        elif url not in _warned:
            _warned.add(url)
            log.warning("GeoTrace custom tile URL is not usable (https, {z} {x} {y} and a real host needed)")
    return found


def _kind(data: bytes) -> str | None:
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    return None


def _ttl_s(headers: Any, now_ms: int) -> int:
    """Seconds the upstream says the tile stays fresh (0 when it says nothing usable)."""
    match = re.search(r"(?:^|[,\s])max-age=(\d+)", headers.get("Cache-Control") or "", re.IGNORECASE)
    if match:
        return int(match.group(1))
    expires = headers.get("Expires")
    if expires:
        try:
            when = parsedate_to_datetime(expires)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return max(int(when.timestamp() - now_ms / 1000), 0)
        except (TypeError, ValueError):
            return 0
    return 0


class _Flight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: tuple[bytes, str] | None = None


class TileCache:
    def __init__(self, folder: Path, cap_bytes: int, clock: Any, opener: Opener | None = None) -> None:
        self.folder = folder
        self.cap_bytes = cap_bytes
        self.opener: Opener = opener if opener is not None else _urlopen
        self._clock = clock
        self._lock = threading.Lock()  # the in-flight map, the semaphores and the last error
        self._flights: dict[tuple[str, int, int, int], _Flight] = {}
        self._gates: dict[str, threading.BoundedSemaphore] = {}
        self._error: tuple[str, int] | None = None
        self._ready = False

    def set_cap(self, cap_bytes: int) -> None:
        self.cap_bytes = cap_bytes

    def last_error(self) -> tuple[str, int] | None:
        with self._lock:
            return self._error

    def get(self, source: TileSource, z: int, x: int, y: int) -> tuple[bytes, str] | None:
        """The tile's bytes and content type, or None when it cannot be had (the route answers 502)."""
        row = self._row(source.name, z, x, y)
        if row is not None and row["expires_ms"] > self._clock.now_ms():
            hit = self._read(source, z, x, y)
            if hit is not None:
                self._touch(source.name, z, x, y)
                return hit
        key = (source.name, z, x, y)
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight()
        if not leader:
            flight.done.wait(TIMEOUT_S * 3)
            return flight.result
        try:
            flight.result = self._fetch(source, z, x, y, row)
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()
        return flight.result

    # -- upstream ------------------------------------------------------------------------------

    def _fetch(
        self, source: TileSource, z: int, x: int, y: int, row: sqlite3.Row | None
    ) -> tuple[bytes, str] | None:
        stale = self._read(source, z, x, y) if row is not None else None
        url = source.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        headers = {"User-Agent": USER_AGENT, "Accept": "image/png,image/jpeg"}
        if stale is not None and row is not None:
            if row["etag"]:
                headers["If-None-Match"] = row["etag"]
            if row["last_modified"]:
                headers["If-Modified-Since"] = row["last_modified"]
        request = urllib.request.Request(url, headers=headers)
        with self._gate(source.name):
            try:
                response = self.opener(request, timeout=TIMEOUT_S)
            except urllib.error.HTTPError as error:
                if error.code == 304 and stale is not None:
                    return self._refresh(source, z, x, y, error.headers, stale)
                return stale
            except (OSError, ValueError, http.client.HTTPException):
                return stale
            try:
                return self._accept(source, z, x, y, response, stale)
            except (OSError, ValueError, http.client.HTTPException):
                return stale
            finally:
                with contextlib.suppress(Exception):
                    response.close()

    def _accept(
        self, source: TileSource, z: int, x: int, y: int, response: Any, stale: tuple[bytes, str] | None
    ) -> tuple[bytes, str] | None:
        headers = response.headers
        if headers.get("x-blocked") is not None:
            label = "OpenStreetMap" if source.name == "osm" else source.name
            self._set_error(f"{label} refused the request")
            return stale
        status = getattr(response, "status", 200)
        if status == 304 and stale is not None:
            return self._refresh(source, z, x, y, headers, stale)
        if status != 200:
            return stale
        data = response.read(MAX_TILE_BYTES + 1)
        kind = _kind(data)
        if len(data) >= MAX_TILE_BYTES or kind is None:
            return stale
        self._set_error(None)
        self._store(source, z, x, y, data, kind, headers)
        return data, kind

    def _refresh(
        self, source: TileSource, z: int, x: int, y: int, headers: Any, stale: tuple[bytes, str]
    ) -> tuple[bytes, str]:
        self._set_error(None)
        with self._db() as db:
            db.execute(
                "UPDATE tile SET expires_ms=?, etag=COALESCE(?, etag),"
                " last_modified=COALESCE(?, last_modified), last_used_ms=?"
                " WHERE source=? AND z=? AND x=? AND y=?",
                (
                    self._expiry(source, headers),
                    headers.get("ETag"),
                    headers.get("Last-Modified"),
                    self._clock.now_ms(),
                    source.name,
                    z,
                    x,
                    y,
                ),
            )
        return stale

    def _expiry(self, source: TileSource, headers: Any) -> int:
        now = self._clock.now_ms()
        return int(now + 1000 * max(source.min_fresh_s, _ttl_s(headers, now)))

    def _gate(self, name: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._gates.setdefault(name, threading.BoundedSemaphore(PER_SOURCE_LIMIT))

    def _set_error(self, message: str | None) -> None:
        with self._lock:
            self._error = None if message is None else (message, self._clock.now_ms())

    # -- disk and index ------------------------------------------------------------------------

    def _path(self, source: TileSource, z: int, x: int, y: int) -> Path:
        return self.folder / source.name / str(z) / str(x) / f"{y}.{source.ext}"

    def _db(self) -> _Db:
        self.folder.mkdir(parents=True, exist_ok=True)
        db = _Db(self.folder / "index.sqlite3")
        if not self._ready:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tile (source TEXT, z INT, x INT, y INT, ctype TEXT,"
                " expires_ms INT, etag TEXT, last_modified TEXT, size INT, last_used_ms INT, ext TEXT,"
                " PRIMARY KEY (source, z, x, y))"
            )
            self._ready = True
        return db

    def _row(self, source: str, z: int, x: int, y: int) -> sqlite3.Row | None:
        with self._db() as db:
            row: sqlite3.Row | None = db.execute(
                "SELECT * FROM tile WHERE source=? AND z=? AND x=? AND y=?", (source, z, x, y)
            ).fetchone()
        return row

    def _read(self, source: TileSource, z: int, x: int, y: int) -> tuple[bytes, str] | None:
        try:
            data = self._path(source, z, x, y).read_bytes()
        except OSError:
            return None
        kind = _kind(data)
        return (data, kind) if kind is not None else None

    def _touch(self, source: str, z: int, x: int, y: int) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE tile SET last_used_ms=? WHERE source=? AND z=? AND x=? AND y=?",
                (self._clock.now_ms(), source, z, x, y),
            )

    def _store(
        self, source: TileSource, z: int, x: int, y: int, data: bytes, kind: str, headers: Any
    ) -> None:
        path = self._path(source, z, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(f"{path.name}.{threading.get_ident()}.part")
        part.write_bytes(data)
        os.replace(part, path)
        now = self._clock.now_ms()
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO tile VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source.name, z, x, y, kind, self._expiry(source, headers),
                    headers.get("ETag"), headers.get("Last-Modified"), len(data), now, source.ext,
                ),
            )  # fmt: skip
        self._evict()

    def _evict(self) -> None:
        with self._db() as db:
            total = db.execute("SELECT COALESCE(SUM(size), 0) FROM tile").fetchone()[0]
            if total <= self.cap_bytes:
                return
            target = self.cap_bytes * EVICT_TO
            for row in db.execute("SELECT * FROM tile ORDER BY last_used_ms").fetchall():
                if total <= target:
                    break
                path = (
                    self.folder / row["source"] / str(row["z"]) / str(row["x"]) / f"{row['y']}.{row['ext']}"
                )
                with contextlib.suppress(OSError):
                    path.unlink()
                db.execute(
                    "DELETE FROM tile WHERE source=? AND z=? AND x=? AND y=?",
                    (row["source"], row["z"], row["x"], row["y"]),
                )
                total -= row["size"]


class _Db:
    """A short-lived connection used as a context manager: commits on success, always closes."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path, timeout=15)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def __enter__(self) -> _Db:
        return self

    def __exit__(self, kind: Any, error: Any, trace: Any) -> None:
        try:
            if kind is None:
                self._conn.commit()
        finally:
            self._conn.close()


def _urlopen(request: urllib.request.Request, timeout: float = TIMEOUT_S) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)
