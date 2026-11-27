"""Download, verify, swap and report the DB-IP Lite databases kept in the plugin's files folder."""

from __future__ import annotations

import contextlib
import gzip
import http.client
import os
import re
import threading
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import maxminddb

from .geo import DbipLocator

USER_AGENT = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
_URL = "https://download.db-ip.com/free/dbip-{kind}-lite-{year}-{month:02d}.mmdb.gz"
_KINDS = ("city", "asn")
_MIN_RECORDS = 1000
_TIMEOUT_S = 60
_CHUNK = 1 << 16
_FILE = re.compile(r"^dbip-(city|asn)-lite-(\d{4})-(\d{2})\.mmdb$")


class _NotPublished(Exception):
    """The month's file is not on the server yet (HTTP 404)."""


class _Rejected(Exception):
    """A download that must not replace the current file; the text is shown to the user."""


class _Cancelled(Exception):
    """stop() was called: abandon the download without touching the files in place."""


class GeoData:
    def __init__(
        self,
        folder: Path,
        clock: Any,
        opener: Callable[..., Any] = urllib.request.urlopen,
        open_reader: Callable[[Path], Any] = maxminddb.open_database,
    ) -> None:
        self._folder = folder
        self._clock = clock
        self._opener = opener
        self._open_reader = open_reader
        self._lock = threading.RLock()  # short: the locator, status fields and the swap
        self._update_lock = threading.Lock()  # one download run at a time
        self._cancelled = threading.Event()
        self._locator: DbipLocator | None = None
        self._last_error: str | None = None
        self._checked_ms: int | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "city": self._newest_good("city"),
                "asn": self._newest_good("asn"),
                "last_error": self._last_error,
                "checked_ms": self._checked_ms,
            }

    def ensure(self) -> None:
        """Download whichever of the two files is missing altogether."""
        with self._lock:
            missing = [kind for kind in _KINDS if self._newest_good(kind) is None]
        if missing:
            self._run(missing, force=False)

    def update(self, force: bool = False) -> None:
        self._run(list(_KINDS), force=force)

    def locator(self) -> DbipLocator:
        with self._lock:
            if self._locator is None:
                city = self._newest_good("city")
                asn = self._newest_good("asn")
                self._locator = DbipLocator(
                    Path(city["path"]) if city else None,
                    Path(asn["path"]) if asn else None,
                    open_reader=self._open_reader,
                )
            return self._locator

    def cancel(self) -> None:
        """Make a running or later update stop at its next chunk and write nothing more."""
        self._cancelled.set()

    def stop(self, timeout_s: float) -> bool:
        """Cancel, then wait up to ``timeout_s`` for a running update to let go. False if it still runs."""
        self.cancel()
        if not self._update_lock.acquire(timeout=max(timeout_s, 0.0)):
            return False
        self._update_lock.release()
        return True

    def close(self) -> None:
        with self._lock:
            locator, self._locator = self._locator, None
            if locator is not None:
                locator.close()

    # -- internals ---------------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock.now_ms() / 1000, UTC)

    def _run(self, kinds: list[str], force: bool) -> None:
        if not self._update_lock.acquire(blocking=False):
            return  # another update is already running
        try:
            if not self._cancelled.is_set():
                self._run_locked(kinds, force)
        except _Cancelled:
            pass
        finally:
            self._update_lock.release()

    def _run_locked(self, kinds: list[str], force: bool) -> None:
        now = self._now()
        with self._lock:
            self._checked_ms = int(self._clock.now_ms())
        this_month = (now.year, now.month)
        last_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        errors: list[str] = []
        self._folder.mkdir(parents=True, exist_ok=True)
        for kind in kinds:
            try:
                self._update_kind(kind, this_month, last_month, force)
            except _Cancelled:
                raise
            except _Rejected as exc:
                errors.append(f"{kind}: {exc}")
            except Exception as exc:  # one kind's failure must never stop the other
                errors.append(f"{kind}: unexpected problem ({type(exc).__name__}: {exc})")
        with self._lock:
            self._last_error = "; ".join(errors) if errors else None

    def _update_kind(
        self,
        kind: str,
        this_month: tuple[int, int],
        last_month: tuple[int, int],
        force: bool,
    ) -> None:
        if not force and self._path(kind, *this_month).exists() and self._is_good(kind, this_month):
            return
        try:
            self._fetch(kind, this_month)
            return
        except _NotPublished:
            pass  # early in the month the new file may not exist yet; last month's is fine
        if not force and self._path(kind, *last_month).exists() and self._is_good(kind, last_month):
            return
        try:
            self._fetch(kind, last_month)
        except _NotPublished:
            raise _Rejected("DB-IP has not published a file for this or last month") from None

    def _path(self, kind: str, year: int, month: int) -> Path:
        return self._folder / f"dbip-{kind}-lite-{year}-{month:02d}.mmdb"

    def _is_good(self, kind: str, month: tuple[int, int]) -> bool:
        return self._check(self._path(kind, *month)) is None

    def _check(self, path: Path) -> str | None:
        """Open the file once and make sure it holds a real database; None means good."""
        try:
            reader = self._open_reader(path)
        except Exception as exc:  # maxminddb.InvalidDatabaseError, ValueError, OSError
            return f"the file is not a readable database ({exc})"
        try:
            count = reader.metadata().node_count
        except Exception as exc:
            return f"the file is not a readable database ({exc})"
        finally:
            reader.close()
        if count < _MIN_RECORDS:
            return f"the database looks incomplete ({count} records)"
        return None

    def _fetch(self, kind: str, month: tuple[int, int]) -> None:
        year, number = month
        final = self._path(kind, year, number)
        packed = final.with_name(final.name + ".gz.part")
        part = final.with_name(final.name + ".part")
        request = urllib.request.Request(
            _URL.format(kind=kind, year=year, month=number),
            headers={"User-Agent": USER_AGENT},
        )
        try:
            self._download(request, packed)
            self._gunzip(packed, part)
            problem = self._check(part)
            if problem is not None:
                raise _Rejected(f"DB-IP sent a bad file: {problem}")
            self._check_cancelled()
            self._swap(kind, part, final)
        finally:
            for leftover in (packed, part):
                leftover.unlink(missing_ok=True)

    def _download(self, request: urllib.request.Request, target: Path) -> None:
        try:
            response = self._opener(request, timeout=_TIMEOUT_S)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise _NotPublished from None
            raise _Rejected(f"DB-IP answered HTTP {exc.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise _Rejected(f"could not reach DB-IP ({reason})") from None
        try:
            with target.open("wb") as out:
                self._copy(response, out)
        except (OSError, http.client.HTTPException) as exc:
            raise _Rejected(f"the download did not finish ({exc!r})") from None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise _Cancelled

    def _copy(self, source: Any, out: Any) -> None:
        """shutil.copyfileobj, except that it gives up between chunks once stop() was called."""
        while chunk := source.read(_CHUNK):
            self._check_cancelled()
            out.write(chunk)
        self._check_cancelled()

    def _gunzip(self, source: Path, target: Path) -> None:
        try:
            with gzip.open(source, "rb") as src, target.open("wb") as out:
                self._copy(src, out)
        except (OSError, EOFError, zlib.error):
            raise _Rejected("DB-IP sent something that is not a complete database file") from None

    def _swap(self, kind: str, part: Path, final: Path) -> None:
        """Put the checked file in place, then drop the older months of that kind."""
        with self._lock:
            self._check_cancelled()
            # The old locator keeps its files mapped (locked on Windows): let go before touching them.
            locator, self._locator = self._locator, None
            if locator is not None:
                locator.close()
            try:
                os.replace(part, final)
            except OSError as exc:
                raise _Rejected(f"could not put the new file in place ({exc})") from None
            for path in self._folder.iterdir():
                match = _FILE.match(path.name)
                if match and match.group(1) == kind and path.name < final.name:
                    # a stale file we could not remove is harmless; the newest wins
                    with contextlib.suppress(OSError):
                        path.unlink()

    def _newest_good(self, kind: str) -> dict[str, Any] | None:
        if not self._folder.exists():
            return None
        found: list[tuple[str, Path]] = []
        for path in self._folder.iterdir():
            match = _FILE.match(path.name)
            if match and match.group(1) == kind:
                found.append((f"{match.group(2)}-{match.group(3)}", path))
        for month, path in sorted(found, reverse=True):
            if self._check(path) is None:
                return {"month": month, "path": str(path)}
        return None
