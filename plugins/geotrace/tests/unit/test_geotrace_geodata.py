from __future__ import annotations

import gzip
import io
import threading
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from netview_local_plugins.geotrace.geodata import GeoData

from netview.sdk.testing.fakes import FakeClock

UA = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"


def ms(year: int, month: int, day: int = 15) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


class FakeReader:
    """Reads 'mmdb:<node_count>' files; anything else is not a database."""

    def __init__(self, path: Any) -> None:
        raw = Path(str(path)).read_bytes()
        if not raw.startswith(b"mmdb:"):
            raise ValueError("not a database")
        self.nodes = int(raw.split(b":")[1])
        self.closed = False

    def metadata(self) -> Any:
        return SimpleNamespace(node_count=self.nodes)

    def get(self, ip: str) -> Any:
        return None

    def close(self) -> None:
        self.closed = True


def payload(nodes: int = 5000) -> bytes:
    return gzip.compress(b"mmdb:" + str(nodes).encode())


class FakeOpener:
    """Maps URL to bytes (or an exception to raise); unknown URLs are 404."""

    def __init__(self, table: dict[str, Any]) -> None:
        self.table = table
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        entry = self.table.get(request.full_url)
        if entry is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        if isinstance(entry, Exception):
            raise entry
        return io.BytesIO(entry)


def url(kind: str, y: int, m: int) -> str:
    return f"https://download.db-ip.com/free/dbip-{kind}-lite-{y}-{m:02d}.mmdb.gz"


def both(y: int, m: int, body: Any) -> dict[str, Any]:
    return {url("city", y, m): body, url("asn", y, m): body}


def make(
    tmp_path: Path, table: dict[str, Any], now: int = ms(2026, 11)
) -> tuple[GeoData, FakeOpener, FakeClock]:
    opener = FakeOpener(table)
    clock = FakeClock(now)
    data = GeoData(tmp_path / "geo", clock, opener=opener, open_reader=FakeReader)
    return data, opener, clock


def names(tmp_path: Path) -> list[str]:
    folder = tmp_path / "geo"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_ensure_downloads_both_files(tmp_path: Path) -> None:
    data, opener, _ = make(tmp_path, both(2026, 11, payload()))
    data.ensure()
    assert names(tmp_path) == ["dbip-asn-lite-2026-11.mmdb", "dbip-city-lite-2026-11.mmdb"]
    status = data.status()
    assert status["city"]["month"] == "2026-11"
    assert status["asn"]["month"] == "2026-11"
    assert status["last_error"] is None
    assert status["checked_ms"] == ms(2026, 11)
    assert opener.requests
    assert all(r.get_header("User-agent") == UA for r in opener.requests)


def test_ensure_does_nothing_when_files_exist(tmp_path: Path) -> None:
    data, opener, _ = make(tmp_path, both(2026, 11, payload()))
    data.ensure()
    n = len(opener.requests)
    data.ensure()
    assert len(opener.requests) == n


def test_update_skips_when_current_month_present_unless_forced(tmp_path: Path) -> None:
    data, opener, _ = make(tmp_path, both(2026, 11, payload()))
    data.update()
    n = len(opener.requests)
    data.update()
    assert len(opener.requests) == n
    data.update(force=True)
    assert len(opener.requests) == n + 2
    assert names(tmp_path) == ["dbip-asn-lite-2026-11.mmdb", "dbip-city-lite-2026-11.mmdb"]


def test_new_month_replaces_old_after_it_opens(tmp_path: Path) -> None:
    table = {**both(2026, 10, payload()), **both(2026, 11, payload())}
    data, _, clock = make(tmp_path, table, now=ms(2026, 10))
    data.update()
    old = data.locator()
    clock.advance(ms(2026, 11) - ms(2026, 10))
    data.update()
    assert names(tmp_path) == ["dbip-asn-lite-2026-11.mmdb", "dbip-city-lite-2026-11.mmdb"]
    assert data.locator() is not old
    assert data.status()["city"]["month"] == "2026-11"


def test_html_body_keeps_old_file_and_records_error(tmp_path: Path) -> None:
    table = {**both(2026, 10, payload()), **both(2026, 11, b"<html>Error</html>")}
    data, _, clock = make(tmp_path, table, now=ms(2026, 10))
    data.update()
    clock.advance(ms(2026, 11) - ms(2026, 10))
    data.update()
    assert names(tmp_path) == ["dbip-asn-lite-2026-10.mmdb", "dbip-city-lite-2026-10.mmdb"]
    status = data.status()
    assert status["last_error"]
    assert status["city"]["month"] == "2026-10"


def test_truncated_gzip_keeps_old_file(tmp_path: Path) -> None:
    good = payload()
    table = {**both(2026, 10, good), **both(2026, 11, good[:-8])}
    data, _, clock = make(tmp_path, table, now=ms(2026, 10))
    data.update()
    clock.advance(ms(2026, 11) - ms(2026, 10))
    data.update()
    assert names(tmp_path) == ["dbip-asn-lite-2026-10.mmdb", "dbip-city-lite-2026-10.mmdb"]
    assert data.status()["last_error"]


def test_a_download_over_the_packed_cap_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("netview_local_plugins.geotrace.geodata.MAX_PACKED_BYTES", 10)
    data, _, _ = make(tmp_path, both(2026, 11, payload()))
    data.update()
    assert names(tmp_path) == []
    assert "bigger than expected" in (data.status()["last_error"] or "")


def test_a_file_over_the_unpacked_cap_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("netview_local_plugins.geotrace.geodata.MAX_UNPACKED_BYTES", 5)
    data, _, _ = make(tmp_path, both(2026, 11, payload()))
    data.update()
    assert names(tmp_path) == []
    assert "bigger than expected" in (data.status()["last_error"] or "")


def test_on_swap_runs_once_per_replaced_file_and_not_for_a_rejected_download(tmp_path: Path) -> None:
    data, _, _ = make(tmp_path, both(2026, 11, payload()))
    swaps: list[int] = []
    data.on_swap = lambda: swaps.append(1)
    data.update()
    assert len(swaps) == 2  # city and asn
    bad, _, _ = make(tmp_path / "bad", both(2026, 11, payload(10)))
    bad.on_swap = lambda: swaps.append(1)
    bad.update()
    assert len(swaps) == 2


def test_too_few_records_is_rejected(tmp_path: Path) -> None:
    data, _, _ = make(tmp_path, both(2026, 11, payload(10)))
    data.update()
    assert names(tmp_path) == []
    assert data.status()["last_error"]
    assert data.status()["city"] is None


def test_this_month_404_falls_back_to_last_month(tmp_path: Path) -> None:
    data, opener, _ = make(tmp_path, both(2026, 10, payload()), now=ms(2026, 11, 2))
    data.update()
    assert names(tmp_path) == ["dbip-asn-lite-2026-10.mmdb", "dbip-city-lite-2026-10.mmdb"]
    assert data.status()["city"]["month"] == "2026-10"
    assert data.status()["last_error"] is None
    assert url("city", 2026, 11) in [r.full_url for r in opener.requests]


def test_january_falls_back_to_december(tmp_path: Path) -> None:
    data, _, _ = make(tmp_path, both(2025, 12, payload()), now=ms(2026, 1, 2))
    data.update()
    assert data.status()["city"]["month"] == "2025-12"


def test_network_error_is_plain_words(tmp_path: Path) -> None:
    data, _, _ = make(tmp_path, both(2026, 11, urllib.error.URLError("no route")))
    data.update()
    assert "no route" in (data.status()["last_error"] or "")


def test_unreadable_newest_file_is_skipped_for_newest_good(tmp_path: Path) -> None:
    data, _, _ = make(tmp_path, {})
    folder = tmp_path / "geo"
    folder.mkdir()
    (folder / "dbip-city-lite-2026-10.mmdb").write_bytes(b"mmdb:5000")
    (folder / "dbip-city-lite-2026-11.mmdb").write_bytes(b"garbage")
    assert data.status()["city"]["month"] == "2026-10"


def test_locator_is_reused_and_close_is_safe_twice(tmp_path: Path) -> None:
    data, _, _ = make(tmp_path, both(2026, 11, payload()))
    data.ensure()
    loc = data.locator()
    assert data.locator() is loc
    data.close()
    data.close()
    assert data.locator() is not loc


@pytest.mark.parametrize("bad", [b"", b"\x1f\x8b"])
def test_empty_or_stub_body_fails(tmp_path: Path, bad: bytes) -> None:
    data, _, _ = make(tmp_path, both(2026, 11, bad))
    data.update()
    assert data.status()["last_error"]
    assert names(tmp_path) == []


class _Streaming:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def read(self, size: int = -1) -> bytes:
        raise self.error

    def close(self) -> None:
        pass


def _seed_old(tmp_path: Path, data_table: dict[str, Any], now: int) -> tuple[GeoData, Any, FakeClock]:
    data, opener, clock = make(tmp_path, data_table, now=now)
    data.update()
    clock.advance(ms(2026, 11) - ms(2026, 10))
    return data, opener, clock


def test_incomplete_read_sets_error_and_other_kind_still_tried(tmp_path: Path) -> None:
    import http.client

    table = {
        **both(2026, 10, payload()),
        url("city", 2026, 11): _Streaming(http.client.IncompleteRead(b"x")),
        url("asn", 2026, 11): payload(),
    }

    class Opener(FakeOpener):
        def __call__(self, request: Any, timeout: float | None = None) -> Any:
            entry = self.table.get(request.full_url)
            if isinstance(entry, _Streaming):
                self.requests.append(request)
                return entry
            return super().__call__(request, timeout)

    opener = Opener(table)
    clock = FakeClock(ms(2026, 10))
    data = GeoData(tmp_path / "geo", clock, opener=opener, open_reader=FakeReader)
    data.update()
    clock.advance(ms(2026, 11) - ms(2026, 10))
    data.update()
    status = data.status()
    assert status["last_error"]
    assert "city" in status["last_error"]
    assert status["city"]["month"] == "2026-10"
    assert status["asn"]["month"] == "2026-11"
    assert (tmp_path / "geo" / "dbip-city-lite-2026-10.mmdb").exists()


def test_replace_failure_keeps_old_files_and_tries_other_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    table = {**both(2026, 10, payload()), **both(2026, 11, payload())}
    data, _, _clock = _seed_old(tmp_path, table, ms(2026, 10))
    real = os.replace
    attempted: list[str] = []

    def failing(src: Any, dst: Any) -> None:
        attempted.append(Path(str(dst)).name)
        if "city" in str(dst):
            raise PermissionError("locked by antivirus")
        real(src, dst)

    monkeypatch.setattr(os, "replace", failing)
    data.update()
    status = data.status()
    assert "locked by antivirus" in status["last_error"]
    assert status["city"]["month"] == "2026-10"
    assert status["asn"]["month"] == "2026-11"
    assert any("asn" in n for n in attempted)


def test_unexpected_exception_is_recorded_and_other_kind_continues(tmp_path: Path) -> None:
    class Boom(FakeOpener):
        def __call__(self, request: Any, timeout: float | None = None) -> Any:
            if "city" in request.full_url:
                raise RuntimeError("surprise")
            return super().__call__(request, timeout)

    opener = Boom(both(2026, 11, payload()))
    data = GeoData(tmp_path / "geo", FakeClock(ms(2026, 11)), opener=opener, open_reader=FakeReader)
    data.update()
    status = data.status()
    assert "surprise" in status["last_error"]
    assert status["asn"]["month"] == "2026-11"


def test_locator_and_status_do_not_wait_for_a_running_download(tmp_path: Path) -> None:
    import threading

    entered = threading.Event()
    release = threading.Event()

    class Slow(FakeOpener):
        def __call__(self, request: Any, timeout: float | None = None) -> Any:
            entered.set()
            assert release.wait(10)
            return super().__call__(request, timeout)

    opener = Slow(both(2026, 11, payload()))
    data = GeoData(tmp_path / "geo", FakeClock(ms(2026, 11)), opener=opener, open_reader=FakeReader)
    worker = threading.Thread(target=data.update)
    worker.start()
    try:
        assert entered.wait(5)
        results: list[Any] = []

        def probe() -> None:
            results.append(data.status())
            results.append(data.locator())

        t = threading.Thread(target=probe)
        t.start()
        t.join(2)
        assert not t.is_alive(), "status/locator blocked behind the download"
        assert len(results) == 2

        second = threading.Thread(target=data.update)
        second.start()
        second.join(2)
        assert not second.is_alive(), "second update should return at once"
    finally:
        release.set()
        worker.join(10)
    assert len([r for r in opener.requests if "city" in r.full_url]) == 1


class SlowBody:
    """A download that hands out one chunk, then calls ``on_second_read`` before the next read."""

    def __init__(self, on_second_read: Callable[[], None]) -> None:
        self.reads = 0
        self.on_second_read = on_second_read
        self.data = io.BytesIO(payload())

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if self.reads == 2:
            self.on_second_read()
        return self.data.read(8) if self.reads < 3 else self.data.read(size)

    def close(self) -> None:
        pass


def test_cancel_stops_a_download_between_chunks_and_leaves_nothing_behind(tmp_path: Path) -> None:
    holder: list[GeoData] = []
    bodies: list[SlowBody] = []

    def opener(request: Any, timeout: float | None = None) -> Any:
        body = SlowBody(lambda: holder[0].cancel())
        bodies.append(body)
        return body

    data = GeoData(tmp_path / "geo", FakeClock(ms(2026, 11)), opener=opener, open_reader=FakeReader)
    holder.append(data)
    data.update()
    assert list((tmp_path / "geo").iterdir()) == []
    assert data.status()["city"] is None and data.status()["last_error"] is None
    assert len(bodies) == 1  # the cancelled run did not go on to the next file


def test_a_cancelled_geodata_does_not_start_another_update(tmp_path: Path) -> None:
    data, opener, _ = make(tmp_path, both(2026, 11, payload()))
    data.cancel()
    data.update()
    assert opener.requests == []


def test_stop_waits_for_the_running_update_and_it_writes_nothing_afterwards(tmp_path: Path) -> None:
    started, release = threading.Event(), threading.Event()

    class Blocking:
        def __init__(self) -> None:
            self.first = True

        def read(self, size: int = -1) -> bytes:
            started.set()
            release.wait(5)
            return b""

        def close(self) -> None:
            pass

    data = GeoData(
        tmp_path / "geo",
        FakeClock(ms(2026, 11)),
        opener=lambda r, timeout=None: Blocking(),
        open_reader=FakeReader,
    )
    worker = threading.Thread(target=data.update)
    worker.start()
    assert started.wait(5)
    assert data.stop(0.05) is False  # still running: stop reports it could not wait it out
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert data.stop(1.0) is True
    assert list((tmp_path / "geo").iterdir()) == []
