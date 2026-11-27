"""The Cesium bundle: a release asset downloaded once and served from NetView's own origin.

NetView's CSP forbids ``unsafe-eval``, blob workers and wasm, and a plugin install downloads the whole repo,
so Cesium is not committed. ``tools/build_cesium_bundle.py`` makes a trimmed, patched zip; this module fetches
it on first use into ``<files_dir>/cesium/<version>/`` after checking its size and SHA-256.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

USER_AGENT = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
CESIUM_VERSION = "1.144.0"
# Filled in by a small follow-up commit once the owner has published the asset. An empty URL means "not yet".
BUNDLE_URL = ""
BUNDLE_SHA256 = ""
BUNDLE_BYTES = 0

ENTRY_FILE = "Cesium.js"
MAX_UNPACKED_BYTES = 512 * 1024 * 1024
STOP_WAIT_S = 5.0
_TIMEOUT_S = 60
_CHUNK = 1 << 16
_CONTENT_TYPES = {  # pinned: Windows' registry can map some of these oddly, and nosniff would then block them
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
}

Opener = Callable[..., Any]


class _Rejected(Exception):
    """A download that must not be installed; the text is shown to the user."""


class _Cancelled(Exception):
    """stop() was called: abandon the download and leave nothing behind."""


def default_opener(request: urllib.request.Request, timeout: float = _TIMEOUT_S) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def content_type(path: Path) -> str:
    """The media type for a served file; ``mimetypes`` plus the types browsers need for Cesium."""
    suffix = path.suffix.lower()
    return _CONTENT_TYPES.get(suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def unsafe_name(name: str) -> bool:
    """True for a path that could leave its folder: absolute, ``..``, a drive letter, a backslash or a NUL."""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name or ":" in name:
        return True
    return any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))


class BundleManager:
    def __init__(
        self,
        folder: Path,
        opener: Opener = default_opener,
        url: str | None = None,
        sha256: str | None = None,
        size: int | None = None,
        version: str = CESIUM_VERSION,
    ) -> None:
        self.folder = folder
        self._opener = opener
        self._url = BUNDLE_URL if url is None else url
        self._sha256 = (BUNDLE_SHA256 if sha256 is None else sha256).lower()
        self._size = BUNDLE_BYTES if size is None else size
        self._version = version
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._downloading = False
        self._error: str | None = None
        self._stop = threading.Event()

    # -- public ------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            if (self._root() / ENTRY_FILE).is_file():
                state = "ready"
            elif not self._url:
                state = "not_published"
            elif self._downloading:
                state = "downloading"
            elif self._error is not None:
                state = "failed"
            else:
                state = "missing"
            return {
                "state": state,
                "version": self._version,
                "base_url": self.base_url,
                "error": self._error,
            }

    @property
    def version(self) -> str:
        return self._version

    @property
    def base_url(self) -> str:
        """Where the page loads Cesium from, relative to the plugin's API base; the version is in the URL."""
        return f"cesium/{self._version}/"

    def ensure_async(self) -> None:
        """Start the download on a background thread unless it is ready, running, not published or stopped."""
        with self._lock:
            if self._stop.is_set() or self._downloading or not self._url:
                return
            if (self._root() / ENTRY_FILE).is_file():
                return
            self._error = None
            self._downloading = True
            self._thread = threading.Thread(target=self._run, name="geotrace-bundle", daemon=True)
            self._thread.start()

    def wait(self, timeout_s: float) -> bool:
        """Wait for a running download; True when none is running afterwards."""
        thread = self._thread
        if thread is not None:
            thread.join(max(timeout_s, 0.0))
            return not thread.is_alive()
        return True

    def cancel(self) -> None:
        """Make a running or later download stop at its next chunk and write nothing more."""
        self._stop.set()

    def stop(self, wait_s: float = STOP_WAIT_S) -> None:
        """Cancel, then wait up to ``wait_s`` seconds for a running download to let go."""
        self.cancel()
        self.wait(wait_s)

    def path_for(self, rel: str) -> Path | None:
        """The file at ``rel`` under the installed version, or None for anything else (never outside it)."""
        if unsafe_name(rel):
            return None
        root = self._root().resolve()
        try:
            candidate = (root / rel).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                return None
        except (OSError, ValueError):
            return None
        return candidate

    # -- internals ---------------------------------------------------------------------------

    def _root(self) -> Path:
        return self.folder / self._version

    def _run(self) -> None:
        part_file = self.folder / f"{self._version}.zip.part"
        part_dir = self.folder / f"{self._version}.part"
        error: str | None = None
        try:
            self._install(part_file, part_dir)
        except _Cancelled:
            pass
        except _Rejected as exc:
            error = str(exc)
        except zipfile.BadZipFile:
            error = "the download is not a valid zip file"
        except Exception as exc:  # network, disk: shown to the user, never a traceback
            error = str(exc) or type(exc).__name__
        finally:
            part_file.unlink(missing_ok=True)
            shutil.rmtree(part_dir, ignore_errors=True)
            with self._lock:
                self._error = error
                self._downloading = False

    def _install(self, part_file: Path, part_dir: Path) -> None:
        self._check_stop()
        self._fetch(part_file, part_dir)
        self._unzip(part_file, part_dir)
        self._check_stop()
        final = self._root()
        shutil.rmtree(final, ignore_errors=True)
        part_dir.replace(final)

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise _Cancelled

    def _fetch(self, target: Path, part_dir: Path) -> None:
        request = urllib.request.Request(self._url, headers={"User-Agent": USER_AGENT})
        digest = hashlib.sha256()
        total = 0
        response = self._opener(request, timeout=_TIMEOUT_S)
        try:
            self._check_stop()  # before anything touches files_dir: no empty folder after an uninstall
            self.folder.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(part_dir, ignore_errors=True)
            with target.open("wb") as out:
                while True:
                    chunk = response.read(_CHUNK)
                    self._check_stop()
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._size:
                        raise _Rejected("the download is larger than expected (size mismatch)")
                    digest.update(chunk)
                    out.write(chunk)
        finally:
            response.close()
        if total != self._size:
            raise _Rejected("the download is smaller than expected (size mismatch)")
        if digest.hexdigest() != self._sha256:
            raise _Rejected("the download does not match its checksum")

    def _unzip(self, archive: Path, target: Path) -> None:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            for info in infos:
                if unsafe_name(info.orig_filename) or unsafe_name(info.filename):
                    raise _Rejected(f"the download holds an unsafe path: {info.filename!r}")
            if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
                raise _Rejected("the download unpacks to more than expected")
            if ENTRY_FILE not in {i.filename for i in infos}:
                raise _Rejected(f"the download has no {ENTRY_FILE}")
            base = target.resolve()
            target.mkdir(parents=True)
            for info in infos:
                self._check_stop()
                if info.is_dir():
                    continue
                dest = (target / info.filename).resolve()
                if not dest.is_relative_to(base):
                    raise _Rejected(f"the download holds an unsafe path: {info.filename!r}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, dest.open("wb") as out:
                    while chunk := src.read(_CHUNK):
                        self._check_stop()
                        out.write(chunk)
