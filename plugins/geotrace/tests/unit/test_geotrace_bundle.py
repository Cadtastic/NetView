"""The downloaded Cesium bundle: status, a checked download, a zip-slip-proof unzip and a safe lookup."""

from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from pathlib import Path
from typing import Any

import pytest
from netview_local_plugins.geotrace import bundle
from netview_local_plugins.geotrace.bundle import BundleManager

URL = "https://example.test/geotrace-cesium.zip"
VERSION = bundle.CESIUM_VERSION


def make_zip(entries: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo("x")
            info.filename = name  # set after creation: ZipInfo would turn a backslash into a slash on Windows
            z.writestr(info, data)
    return out.getvalue()


GOOD = make_zip({"Cesium.js": b"var Cesium={};", "Workers/createTaskProcessorWorker.js": b"//w"})


class Response:
    def __init__(self, body: bytes, gate: threading.Event | None = None) -> None:
        self._stream = io.BytesIO(body)
        self._gate = gate
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self, n: int = -1) -> bytes:
        if self._gate is not None:
            self._gate.wait(10)
        return self._stream.read(n if n > 0 else 64)

    def close(self) -> None:
        pass


class Opener:
    def __init__(
        self, body: bytes = GOOD, gate: threading.Event | None = None, error: Exception | None = None
    ) -> None:
        self.body = body
        self.gate = gate
        self.error = error
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float = 0) -> Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return Response(self.body, self.gate)


def manager(tmp_path: Path, opener: Opener, body: bytes = GOOD, **kw: Any) -> BundleManager:
    kw.setdefault("url", URL)
    kw.setdefault("sha256", hashlib.sha256(body).hexdigest())
    kw.setdefault("size", len(body))
    return BundleManager(tmp_path / "cesium", opener=opener, **kw)


def settle(m: BundleManager) -> None:
    assert m.wait(10)


def leftovers(tmp_path: Path) -> list[str]:
    folder = tmp_path / "cesium"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_nothing_published_yet_is_not_published_and_never_downloads(tmp_path: Path) -> None:
    assert bundle.BUNDLE_URL == "" and bundle.BUNDLE_SHA256 == "" and bundle.BUNDLE_BYTES == 0
    opener = Opener()
    m = BundleManager(tmp_path / "cesium", opener=opener)
    assert m.status() == {"state": "not_published", "version": VERSION, "error": None}
    m.ensure_async()
    settle(m)
    assert opener.requests == [] and not (tmp_path / "cesium").exists()


def test_missing_then_download_makes_it_ready(tmp_path: Path) -> None:
    opener = Opener()
    m = manager(tmp_path, opener)
    assert m.status()["state"] == "missing"
    m.ensure_async()
    settle(m)
    assert m.status() == {"state": "ready", "version": VERSION, "error": None}
    worker = tmp_path / "cesium" / VERSION / "Workers" / "createTaskProcessorWorker.js"
    assert worker.read_bytes() == b"//w"
    assert leftovers(tmp_path) == [VERSION]
    assert opener.requests[0].get_header("User-agent") == bundle.USER_AGENT
    assert opener.requests[0].full_url == URL


def test_ensure_async_is_a_no_op_when_ready(tmp_path: Path) -> None:
    opener = Opener()
    m = manager(tmp_path, opener)
    m.ensure_async()
    settle(m)
    m.ensure_async()
    settle(m)
    assert len(opener.requests) == 1


def test_only_one_download_at_a_time(tmp_path: Path) -> None:
    gate = threading.Event()
    opener = Opener(gate=gate)
    m = manager(tmp_path, opener)
    m.ensure_async()
    m.ensure_async()
    assert m.status()["state"] == "downloading"
    gate.set()
    settle(m)
    assert len(opener.requests) == 1 and m.status()["state"] == "ready"


def test_bad_sha_fails_and_leaves_nothing_behind(tmp_path: Path) -> None:
    m = manager(tmp_path, Opener(), sha256="0" * 64)
    m.ensure_async()
    settle(m)
    status = m.status()
    assert status["state"] == "failed" and "checksum" in status["error"]
    assert leftovers(tmp_path) == []


def test_wrong_size_fails_and_leaves_nothing_behind(tmp_path: Path) -> None:
    m = manager(tmp_path, Opener(), size=len(GOOD) + 1)
    m.ensure_async()
    settle(m)
    assert m.status()["state"] == "failed" and "size" in m.status()["error"]
    assert leftovers(tmp_path) == []


def test_network_error_fails_and_a_later_call_retries(tmp_path: Path) -> None:
    opener = Opener(error=OSError("no route"))
    m = manager(tmp_path, opener)
    m.ensure_async()
    settle(m)
    assert m.status()["state"] == "failed" and "no route" in m.status()["error"]
    opener.error = None
    m.ensure_async()
    settle(m)
    assert m.status()["state"] == "ready" and m.status()["error"] is None


@pytest.mark.parametrize(
    "name",
    ["../evil.js", "a/../../evil.js", "/abs.js", "C:/evil.js", "C:evil.js", "a\\..\\evil.js", "a\\b.js"],
)
def test_zip_slip_entries_fail_the_whole_download(tmp_path: Path, name: str) -> None:
    body = make_zip({"Cesium.js": b"x", name: b"evil"})
    m = manager(tmp_path, Opener(body), body)
    m.ensure_async()
    settle(m)
    assert m.status()["state"] == "failed"
    assert leftovers(tmp_path) == []
    assert not (tmp_path / "evil.js").exists()


def test_a_zip_without_cesium_js_is_refused(tmp_path: Path) -> None:
    body = make_zip({"Workers/a.js": b"x"})
    m = manager(tmp_path, Opener(body), body)
    m.ensure_async()
    settle(m)
    assert m.status()["state"] == "failed"
    assert leftovers(tmp_path) == []


def test_a_garbage_download_with_the_right_checksum_fails_cleanly(tmp_path: Path) -> None:
    body = b"<html>not a zip</html>"
    m = manager(tmp_path, Opener(body), body)
    m.ensure_async()
    settle(m)
    assert m.status()["state"] == "failed"
    assert leftovers(tmp_path) == []


def test_stop_cancels_a_running_download_and_writes_nothing_more(tmp_path: Path) -> None:
    gate = threading.Event()
    m = manager(tmp_path, Opener(gate=gate))
    m.ensure_async()
    m.stop(0.2)  # the read is blocked: stop must come back within its bound
    gate.set()
    assert m.wait(10)
    m.ensure_async()  # after stop: a no-op
    assert m.wait(10)
    assert not (tmp_path / "cesium" / VERSION).exists()
    assert leftovers(tmp_path) == []


def test_path_for_finds_files_and_refuses_anything_outside(tmp_path: Path) -> None:
    m = manager(tmp_path, Opener())
    m.ensure_async()
    settle(m)
    root = tmp_path / "cesium" / VERSION
    assert m.path_for("Cesium.js") == (root / "Cesium.js").resolve()
    assert m.path_for("Workers/createTaskProcessorWorker.js") is not None
    (tmp_path / "cesium" / "secret.txt").write_text("s")
    for bad in [
        "",
        ".",
        "..",
        "../secret.txt",
        "Workers/../../secret.txt",
        "%2e%2e/secret.txt",
        "C:/x",
        "C:\\x",
        "/etc/passwd",
        "\\Cesium.js",
        "Workers\\createTaskProcessorWorker.js",
        "Workers",
        "nope.js",
        "Cesium.js\x00",
        "//Cesium.js",
    ]:
        assert m.path_for(bad) is None, bad


def test_path_for_is_none_before_the_bundle_is_ready(tmp_path: Path) -> None:
    assert manager(tmp_path, Opener()).path_for("Cesium.js") is None
