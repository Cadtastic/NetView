"""Map tiles fetched by the server and kept on disk (spec 11).

NetView's CSP only lets the browser load images from NetView itself, so every tile comes through here.
Tiles are never prefetched and redirects are never followed. The files and their SQLite index live in
``tile_store.py``; this module decides what to serve, what to fetch and when to give up.
"""

from __future__ import annotations

import contextlib
import http.client
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .settings import GeoTraceSettings, valid_tile_template
from .tile_store import TileRow, TileStore

log = logging.getLogger(__name__)

USER_AGENT = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
MAX_TILE_BYTES = 1_048_576
TIMEOUT_S = 8.0  # one socket operation
GATE_WAIT_S = 2.0  # waiting for one of the source's upstream slots
DEADLINE_S = 10.0  # the whole fetch, once it has a slot
FAIL_WINDOW_S = 30.0  # after a network failure the source answers from disk only
REFUSED_WINDOW_S = 300.0  # after the server refuses us (403, 429 ...) it is left alone for longer
REFUSED_CODES = frozenset({401, 403, 418, 429})
CHUNK = 16_384
PER_SOURCE_LIMIT = 2
EVICT_TO = 0.9
DAY_S = 86_400
MAX_TTL_S = 30 * DAY_S
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

Opener = Callable[..., Any]
Tile = tuple[bytes, str]
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


def sources(settings: GeoTraceSettings) -> dict[str, TileSource]:
    """The sources the admin chose: OSM unless a custom server is set, Sentinel-2 only on request."""
    found: dict[str, TileSource] = {}
    if settings.tile_source != "custom":
        found[_OSM.name] = _OSM
    if settings.base_imagery == "eox_s2":
        found[_EOX.name] = _EOX
    if settings.tile_source == "custom":
        url = settings.custom_tile_url
        if valid_tile_template(url):
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
    """Seconds the upstream says the tile stays fresh (0 when it says nothing usable), at most 30 days."""
    match = re.search(r"(?:^|[,\s])max-age=(\d+)", headers.get("Cache-Control") or "", re.IGNORECASE)
    if match:
        return min(int(match.group(1)), MAX_TTL_S)
    expires = headers.get("Expires")
    if expires:
        try:
            when = parsedate_to_datetime(expires)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return min(max(int(when.timestamp() - now_ms / 1000), 0), MAX_TTL_S)
        except (TypeError, ValueError, OverflowError):
            return 0
    return 0


class TileBusyError(Exception):
    """Every upstream slot for the source stayed taken for too long (the route answers 503)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is a failed fetch: tiles come only from the https address that was configured."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def default_opener(request: urllib.request.Request, timeout: float = TIMEOUT_S) -> Any:
    return _OPENER.open(request, timeout=timeout)


class _Flight:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Tile | None = None
        self.busy = False


class TileCache:
    def __init__(
        self,
        folder: Path,
        cap_bytes: int,
        clock: Any,
        opener: Opener | None = None,
        gate_wait_s: float = GATE_WAIT_S,
        deadline_s: float = DEADLINE_S,
        fail_window_s: float = FAIL_WINDOW_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = TileStore(folder)
        self.cap_bytes = cap_bytes
        self.opener: Opener = opener if opener is not None else default_opener
        self._clock = clock
        self._gate_wait_s = gate_wait_s
        self._deadline_s = deadline_s
        self._fail_window_ms = int(fail_window_s * 1000)
        self._refused_window_ms = int(REFUSED_WINDOW_S * 1000)
        self._monotonic = monotonic
        self._lock = threading.Lock()  # in-flight map, slots, down-until times and the last error
        self._flights: dict[tuple[str, int, int, int], _Flight] = {}
        self._gates: dict[str, threading.BoundedSemaphore] = {}
        self._down_until: dict[str, int] = {}
        self._error: tuple[str, int] | None = None
        self._evict_lock = threading.Lock()
        self._evict_thread: threading.Thread | None = None
        self._evict_again = False

    def set_cap(self, cap_bytes: int) -> None:
        self.cap_bytes = cap_bytes
        self._kick_evict()

    def last_error(self) -> tuple[str, int] | None:
        with self._lock:
            return self._error

    def wait_idle(self, timeout_s: float = 10.0) -> None:
        """Wait for a running background purge (tests and shutdown)."""
        end = self._monotonic() + timeout_s
        while self._evict_thread is not None and self._monotonic() < end:
            self._evict_thread.join(0.05)

    def get(self, source: TileSource, z: int, x: int, y: int) -> Tile | None:
        """The tile's bytes and content type, or None when it cannot be had (the route answers 502).

        Raises ``TileBusyError`` when the source's upstream slots stay taken and no stale tile exists."""
        row = self.store.row(source.name, z, x, y)
        if row is not None and row.expires_ms > self._clock.now_ms():
            hit = self._read(source, z, x, y)
            if hit is not None:
                self.store.touch(source.name, z, x, y, self._clock.now_ms())
                return hit
        key = (source.name, z, x, y)
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if flight is None:
                flight = self._flights[key] = _Flight()
        if not leader:
            flight.done.wait(self._gate_wait_s + self._deadline_s + 1)
            if flight.busy:
                raise TileBusyError
            return flight.result
        try:
            flight.result = self._fetch(source, z, x, y, row)
        except TileBusyError:
            flight.busy = True
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()
        return flight.result

    # -- upstream ------------------------------------------------------------------------------

    def _fetch(self, source: TileSource, z: int, x: int, y: int, row: TileRow | None) -> Tile | None:
        stale = self._read(source, z, x, y) if row is not None else None
        if self._clock.now_ms() < self._down_until.get(source.name, 0):
            return stale  # it failed a moment ago: do not make the next caller wait for it as well
        gate = self._gate(source.name)
        if not gate.acquire(timeout=self._gate_wait_s):
            if stale is not None:
                return stale
            raise TileBusyError
        try:
            return self._upstream(source, z, x, y, row, stale)
        finally:
            gate.release()

    def _upstream(
        self, source: TileSource, z: int, x: int, y: int, row: TileRow | None, stale: Tile | None
    ) -> Tile | None:
        url = source.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        headers = {"User-Agent": USER_AGENT, "Accept": "image/png,image/jpeg"}
        if stale is not None and row is not None:
            if row.etag:
                headers["If-None-Match"] = row.etag
            if row.last_modified:
                headers["If-Modified-Since"] = row.last_modified
        request = urllib.request.Request(url, headers=headers)
        deadline = self._monotonic() + self._deadline_s
        try:
            response = self.opener(request, timeout=min(TIMEOUT_S, self._deadline_s))
        except urllib.error.HTTPError as error:
            if error.code == 304 and stale is not None:
                return self._refresh(source, z, x, y, error.headers, stale)
            blocked = error.headers is not None and error.headers.get("x-blocked") is not None
            try:
                if error.code in REFUSED_CODES or blocked:
                    self._set_error(f"{self._label(source)} refused the request")
                    self._mark_down(source.name, self._refused_window_ms)
                elif error.code >= 500:
                    self._mark_down(source.name)
            finally:
                with contextlib.suppress(Exception):
                    error.close()
            return stale  # a redirect lands here too: it is never followed
        except (OSError, ValueError, http.client.HTTPException):
            self._mark_down(source.name)
            return stale
        try:
            result = self._accept(source, z, x, y, response, stale, deadline)
            self._down_until.pop(source.name, None)
            return result
        except (OSError, ValueError, http.client.HTTPException):
            self._mark_down(source.name)
            return stale
        finally:
            with contextlib.suppress(Exception):
                response.close()

    def _accept(
        self, source: TileSource, z: int, x: int, y: int, response: Any, stale: Tile | None, deadline: float
    ) -> Tile | None:
        headers = response.headers
        if headers.get("x-blocked") is not None:
            self._set_error(f"{self._label(source)} refused the request")
            return stale
        status = getattr(response, "status", 200)
        if status == 304 and stale is not None:
            return self._refresh(source, z, x, y, headers, stale)
        if status != 200:
            return stale
        data = self._read_body(response, deadline)
        kind = _kind(data)
        if len(data) >= MAX_TILE_BYTES or kind is None:
            return stale
        self._set_error(None)
        self.store.put(
            source.name, source.ext, (z, x, y), data, kind, self._expiry(source, headers),
            headers.get("ETag"), headers.get("Last-Modified"), self._clock.now_ms(),
        )  # fmt: skip
        self._kick_evict()
        return data, kind

    def _read_body(self, response: Any, deadline: float) -> bytes:
        """At most ``MAX_TILE_BYTES`` bytes, in chunks, so the total deadline is checked as data arrives."""
        data = bytearray()
        while len(data) < MAX_TILE_BYTES:
            if self._monotonic() >= deadline:
                raise TimeoutError("tile download took too long")
            chunk = response.read(min(CHUNK, MAX_TILE_BYTES - len(data)))
            if not chunk:
                break
            data += chunk
        return bytes(data)

    def _refresh(self, source: TileSource, z: int, x: int, y: int, headers: Any, stale: Tile) -> Tile:
        self._set_error(None)
        self.store.refresh(
            source.name, z, x, y, self._expiry(source, headers), headers.get("ETag"),
            headers.get("Last-Modified"), self._clock.now_ms(),
        )  # fmt: skip
        return stale

    def _expiry(self, source: TileSource, headers: Any) -> int:
        now = self._clock.now_ms()
        return int(now + 1000 * max(source.min_fresh_s, _ttl_s(headers, now)))

    def _read(self, source: TileSource, z: int, x: int, y: int) -> Tile | None:
        data = self.store.read(source.name, source.ext, z, x, y)
        kind = _kind(data) if data is not None else None
        return (data, kind) if data is not None and kind is not None else None

    def _gate(self, name: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._gates.setdefault(name, threading.BoundedSemaphore(PER_SOURCE_LIMIT))

    @staticmethod
    def _label(source: TileSource) -> str:
        return "OpenStreetMap" if source.name == "osm" else source.name

    def _mark_down(self, name: str, window_ms: int | None = None) -> None:
        self._down_until[name] = self._clock.now_ms() + (
            self._fail_window_ms if window_ms is None else window_ms
        )

    def _set_error(self, message: str | None) -> None:
        with self._lock:
            self._error = None if message is None else (message, self._clock.now_ms())

    # -- eviction ------------------------------------------------------------------------------

    def _kick_evict(self) -> None:
        """Purge on a background thread, one at a time, never inside a request."""
        with self._evict_lock:
            self._evict_again = True
            if self._evict_thread is not None:
                return
            thread = threading.Thread(target=self._evict_loop, name="geotrace-tile-evict", daemon=True)
            self._evict_thread = thread
            thread.start()

    def _evict_loop(self) -> None:
        while True:
            with self._evict_lock:
                if not self._evict_again:
                    self._evict_thread = None
                    return
                self._evict_again = False
            try:
                self.store.evict(self.cap_bytes, EVICT_TO)
            except Exception:
                log.exception("GeoTrace tile cache purge failed")
