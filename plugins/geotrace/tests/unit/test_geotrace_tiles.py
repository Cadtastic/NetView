from __future__ import annotations

import http.server
import io
import sqlite3
import threading
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from netview_local_plugins.geotrace import tile_store
from netview_local_plugins.geotrace.settings import GeoTraceSettings
from netview_local_plugins.geotrace.tile_store import TileStore
from netview_local_plugins.geotrace.tiles import (
    TileBusyError,
    TileCache,
    TileSource,
    default_opener,
    sources,
)
from pydantic import ValidationError

from netview.sdk.testing.fakes import FakeClock

UA = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"1" * 100
DAY_MS = 86_400_000
OSM = TileSource("osm", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19, 7 * 86_400, "png", "c")
EOX = TileSource("eox-s2", "https://tiles.example.org/{z}/{y}/{x}.jpg", 14, 86_400, "jpg", "c")


class Response:
    def __init__(self, body: bytes, status: int = 200, **headers: str) -> None:
        self.status = status
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name.replace("_", "-")] = value
        self._body = body
        self._io = io.BytesIO(body)

    def copy(self) -> Response:
        clone = Response(self._body, self.status)
        clone.headers = self.headers
        return clone

    def read(self, n: int = -1) -> bytes:
        return self._io.read(n)

    def close(self) -> None:
        pass


class Opener:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[urllib.request.Request] = []
        self.lock = threading.Lock()

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Any:
        with self.lock:
            self.requests.append(request)
            answer = self.answers[0] if len(self.answers) == 1 else self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer.copy() if isinstance(answer, Response) else answer

    def header(self, index: int, name: str) -> str | None:
        return self.requests[index].get_header(name)


def not_modified(**headers: str) -> urllib.error.HTTPError:
    msg = Message()
    for name, value in headers.items():
        msg[name.replace("_", "-")] = value
    return urllib.error.HTTPError("https://x", 304, "Not Modified", msg, None)


def cache(tmp_path: Path, opener: Opener, cap: int = 10_000_000) -> tuple[TileCache, FakeClock]:
    clock = FakeClock()
    return TileCache(tmp_path / "tiles", cap, clock, opener), clock


def test_miss_fetches_stores_and_a_fresh_hit_skips_the_opener(tmp_path: Path) -> None:
    opener = Opener(Response(PNG, Cache_Control="max-age=100", ETag='"a"'))
    tiles, _ = cache(tmp_path, opener)
    assert tiles.get(OSM, 3, 2, 1) == (PNG, "image/png")
    assert tiles.get(OSM, 3, 2, 1) == (PNG, "image/png")
    assert len(opener.requests) == 1
    assert (tmp_path / "tiles" / "osm" / "3" / "2" / "1.png").read_bytes() == PNG
    assert opener.requests[0].full_url == "https://tile.openstreetmap.org/3/2/1.png"
    assert opener.header(0, "User-agent") == UA


def test_url_template_order_follows_the_source(tmp_path: Path) -> None:
    opener = Opener(Response(JPEG))
    tiles, _ = cache(tmp_path, opener)
    assert tiles.get(EOX, 4, 5, 6) == (JPEG, "image/jpeg")
    assert opener.requests[0].full_url == "https://tiles.example.org/4/6/5.jpg"


def test_minimum_freshness_beats_a_short_max_age(tmp_path: Path) -> None:
    opener = Opener(Response(PNG, Cache_Control="max-age=10"))
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    clock.advance(6 * DAY_MS)
    tiles.get(OSM, 1, 0, 0)
    assert len(opener.requests) == 1


def test_expired_tile_is_revalidated_and_304_keeps_the_bytes(tmp_path: Path) -> None:
    opener = Opener(
        Response(PNG, ETag='"abc"', Last_Modified="Wed, 01 Jan 2026 00:00:00 GMT"),
        not_modified(Cache_Control="max-age=100"),
    )
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    clock.advance(8 * DAY_MS)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    assert opener.header(1, "If-none-match") == '"abc"'
    assert opener.header(1, "If-modified-since") == "Wed, 01 Jan 2026 00:00:00 GMT"
    tiles.get(OSM, 1, 0, 0)  # the 304 refreshed the expiry
    assert len(opener.requests) == 2


def test_a_304_returned_as_a_status_also_refreshes(tmp_path: Path) -> None:
    opener = Opener(Response(PNG, ETag='"abc"'), Response(b"", status=304))
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    clock.advance(8 * DAY_MS)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    tiles.get(OSM, 1, 0, 0)
    assert len(opener.requests) == 2


def test_upstream_failure_serves_the_stale_tile_else_none(tmp_path: Path) -> None:
    opener = Opener(Response(PNG), urllib.error.URLError("down"))
    tiles, clock = cache(tmp_path, opener)
    assert tiles.get(OSM, 1, 0, 0) is not None
    clock.advance(8 * DAY_MS)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    assert tiles.get(OSM, 2, 0, 0) is None  # nothing cached for this one


def test_html_body_is_a_failure_and_nothing_is_cached(tmp_path: Path) -> None:
    opener = Opener(Response(b"<html>nope</html>", Content_Type="image/png"))
    tiles, _ = cache(tmp_path, opener)
    assert tiles.get(OSM, 1, 0, 0) is None
    assert not list((tmp_path / "tiles").rglob("*.png"))
    assert tiles.get(OSM, 1, 0, 0) is None
    assert len(opener.requests) == 2


def test_oversized_body_is_a_failure(tmp_path: Path) -> None:
    opener = Opener(Response(PNG + b"0" * 1_500_000))
    tiles, _ = cache(tmp_path, opener)
    assert tiles.get(OSM, 1, 0, 0) is None
    assert not list((tmp_path / "tiles").rglob("*.png"))


def test_blocked_answer_is_a_failure_that_is_recorded_then_cleared(tmp_path: Path) -> None:
    blocked = Response(
        PNG, X_Blocked="Access denied. See https://operations.osmfoundation.org/policies/tiles/"
    )
    opener = Opener(blocked, Response(PNG))
    tiles, clock = cache(tmp_path, opener)
    assert tiles.last_error() is None
    assert tiles.get(OSM, 1, 0, 0) is None
    assert not list((tmp_path / "tiles").rglob("*.png"))
    assert tiles.last_error() == ("OpenStreetMap refused the request", clock.now_ms())
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    assert tiles.last_error() is None


def test_over_the_cap_the_least_recently_used_go_first(tmp_path: Path) -> None:
    opener = Opener(Response(PNG))
    tiles, clock = cache(tmp_path, opener, cap=len(PNG) * 5)
    for x in range(5):
        clock.advance(1000)
        tiles.get(OSM, 3, x, 0)
    clock.advance(1000)
    tiles.get(OSM, 3, 0, 0)  # tile 0 is now the newest use
    clock.advance(1000)
    tiles.get(OSM, 3, 5, 0)  # six tiles: over the cap, down to 90% of it
    tiles.wait_idle()
    left = sorted(p.parent.name for p in (tmp_path / "tiles" / "osm" / "3").rglob("*.png"))
    assert left == ["0", "3", "4", "5"]  # 1 and 2 were used longest ago
    before = len(opener.requests)
    tiles.get(OSM, 3, 2, 0)  # evicted, so it is fetched again
    assert len(opener.requests) == before + 1


def test_five_concurrent_identical_requests_make_one_upstream_call(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class Slow(Opener):
        def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Any:
            entered.set()
            assert release.wait(10)
            return super().__call__(request, timeout)

    opener = Slow(Response(PNG))
    tiles, _ = cache(tmp_path, opener)
    results: list[Any] = []
    threads = [threading.Thread(target=lambda: results.append(tiles.get(OSM, 2, 1, 1))) for _ in range(5)]
    for t in threads:
        t.start()
    assert entered.wait(10)
    release.set()
    for t in threads:
        t.join(10)
        assert not t.is_alive()
    assert results == [(PNG, "image/png")] * 5
    assert len(opener.requests) == 1


def test_at_most_two_upstream_requests_per_source_at_once(tmp_path: Path) -> None:
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    release = threading.Event()
    two_in = threading.Event()

    def opener(request: urllib.request.Request, timeout: float = 0) -> Any:
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            if state["now"] >= 2:
                two_in.set()
        release.wait(10)
        with lock:
            state["now"] -= 1
        return Response(PNG)

    tiles = TileCache(tmp_path / "tiles", 10_000_000, FakeClock(), opener)
    threads = [threading.Thread(target=tiles.get, args=(OSM, 5, x, 0)) for x in range(6)]
    for t in threads:
        t.start()
    assert two_in.wait(10)
    release.set()
    for t in threads:
        t.join(10)
        assert not t.is_alive()
    assert state["peak"] == 2


def test_index_survives_a_new_cache_object(tmp_path: Path) -> None:
    opener = Opener(Response(PNG))
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    again = TileCache(tmp_path / "tiles", 10_000_000, clock, opener)
    assert again.get(OSM, 1, 0, 0) == (PNG, "image/png")
    assert len(opener.requests) == 1


def test_sources_always_offer_osm_and_eox() -> None:
    found = sources(GeoTraceSettings())
    assert set(found) == {"osm", "eox-s2"}
    assert found["osm"].max_zoom == 19 and found["osm"].min_fresh_s == 7 * 86_400
    assert found["eox-s2"].max_zoom == 14 and found["eox-s2"].url.endswith("/{z}/{y}/{x}.jpg")
    assert found["eox-s2"].min_fresh_s == 86_400


def test_custom_source_needs_a_valid_https_template() -> None:
    ok = GeoTraceSettings(tile_source="custom", custom_tile_url="https://tiles.example.com/{z}/{x}/{y}.png")
    assert sources(ok)["custom"].url == "https://tiles.example.com/{z}/{x}/{y}.png"
    assert sources(GeoTraceSettings(tile_source="osm", custom_tile_url="https://t.example.com/{z}/{x}/{y}"))[
        "osm"
    ]
    assert "custom" not in sources(
        GeoTraceSettings(tile_source="osm", custom_tile_url="https://t.example.com/{z}/{x}/{y}.png")
    )
    for bad in (
        "https://{z}/{x}/{y}",
        "https://{x}.example.com/{z}/{x}/{y}",
        "https:///{z}/{x}/{y}",
        "http://t.example.com/{z}/{x}/{y}",
        "https://t.example.com/{z}/{x}",
        "https://[/{z}/{x}/{y}",
        "https://user:{x}@t.example.com/{z}/{x}/{y}",
        "https://t.example.com:{z}/{x}/{y}",
        "https://t.example.com:99999999/{z}/{x}/{y}",
    ):
        with pytest.raises(ValidationError):
            GeoTraceSettings(tile_source="custom", custom_tile_url=bad)
        settings = GeoTraceSettings.model_construct(
            **{**GeoTraceSettings().model_dump(), "tile_source": "custom", "custom_tile_url": bad}
        )
        assert set(sources(settings)) == {"osm", "eox-s2"}, bad


@pytest.mark.parametrize("claimed", ["osm", "eox-s2"])
def test_source_names_are_stable(claimed: str) -> None:
    assert sources(GeoTraceSettings())[claimed].name == claimed


# -- fix round 1 -----------------------------------------------------------------------------------


class _Redirector(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []  # noqa: RUF012

    def do_GET(self) -> None:
        self.hits.append(self.path)
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/target")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(PNG)

    def log_message(self, *args: Any) -> None:
        pass


def test_the_default_opener_refuses_redirects() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redirector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        with pytest.raises(urllib.error.HTTPError) as caught:
            default_opener(urllib.request.Request(f"http://127.0.0.1:{port}/start"), timeout=5)
        assert caught.value.code == 302
        assert _Redirector.hits == ["/start"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_a_redirect_is_a_failed_fetch_and_the_stale_tile_is_served(tmp_path: Path) -> None:
    redirect = urllib.error.HTTPError("https://x", 302, "Found", Message(), None)
    opener = Opener(Response(PNG), redirect)
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    clock.advance(8 * DAY_MS)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    assert tiles.get(OSM, 2, 0, 0) is None


def test_a_blocked_answer_still_serves_the_stale_tile(tmp_path: Path) -> None:
    blocked = Response(PNG, X_Blocked="Access denied")
    opener = Opener(Response(PNG), blocked)
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    clock.advance(8 * DAY_MS)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    assert tiles.last_error() is not None


class _Blocking:
    """An opener whose calls wait for ``release``; ``inside`` counts the callers that got in."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.inside = threading.Semaphore(0)

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Any:
        self.inside.release()
        self.release.wait(10)
        return Response(PNG)

    def fill_both_slots(self, tiles: TileCache) -> list[threading.Thread]:
        holders = [threading.Thread(target=tiles.get, args=(OSM, 5, x, 0)) for x in (1, 2)]
        for t in holders:
            t.start()
        assert self.inside.acquire(timeout=10) and self.inside.acquire(timeout=10)
        return holders

    def finish(self, holders: list[threading.Thread]) -> None:
        self.release.set()
        for t in holders:
            t.join(10)
            assert not t.is_alive()


def test_a_busy_source_gives_up_waiting_for_a_slot(tmp_path: Path) -> None:
    opener = _Blocking()
    tiles = TileCache(tmp_path / "tiles", 10_000_000, FakeClock(), opener, gate_wait_s=0.1)
    holders = opener.fill_both_slots(tiles)
    try:
        with pytest.raises(TileBusyError):
            tiles.get(OSM, 5, 3, 0)
    finally:
        opener.finish(holders)


def test_a_busy_source_serves_a_stale_tile_when_it_has_one(tmp_path: Path) -> None:
    clock = FakeClock()
    tiles = TileCache(tmp_path / "tiles", 10_000_000, clock, Opener(Response(PNG)), gate_wait_s=0.1)
    tiles.get(OSM, 5, 9, 9)
    clock.advance(8 * DAY_MS)
    opener = _Blocking()
    tiles.opener = opener
    holders = opener.fill_both_slots(tiles)
    try:
        assert tiles.get(OSM, 5, 9, 9) == (PNG, "image/png")
    finally:
        opener.finish(holders)


def test_after_a_network_failure_the_source_fails_fast_for_30_seconds(tmp_path: Path) -> None:
    opener = Opener(urllib.error.URLError("black hole"))
    tiles, clock = cache(tmp_path, opener)
    assert tiles.get(OSM, 1, 0, 0) is None
    assert tiles.get(OSM, 2, 1, 1) is None
    assert len(opener.requests) == 1  # the second tile never reached the upstream
    assert tiles.get(EOX, 2, 1, 1) is None
    assert len(opener.requests) == 2  # another source is not affected
    clock.advance(31_000)
    tiles.get(OSM, 1, 0, 0)
    assert len(opener.requests) == 3


def test_fail_fast_serves_a_stale_tile_without_contacting_the_upstream(tmp_path: Path) -> None:
    opener = Opener(Response(PNG), Response(PNG), TimeoutError("slow"))
    tiles, clock = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    tiles.get(OSM, 1, 1, 0)
    clock.advance(8 * DAY_MS)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")  # the failure, stale served
    assert tiles.get(OSM, 1, 1, 0) == (PNG, "image/png")  # fast, stale
    assert len(opener.requests) == 3


def test_an_http_error_is_not_a_network_failure(tmp_path: Path) -> None:
    missing = urllib.error.HTTPError("https://x", 404, "Not Found", Message(), None)
    opener = Opener(missing)
    tiles, _ = cache(tmp_path, opener)
    assert tiles.get(OSM, 1, 0, 0) is None
    assert tiles.get(OSM, 1, 1, 0) is None
    assert len(opener.requests) == 2


def test_a_slow_trickle_stops_at_the_total_deadline(tmp_path: Path) -> None:
    now = [0.0]

    class Trickle(Response):
        def copy(self) -> Response:
            return self

        def read(self, n: int = -1) -> bytes:
            now[0] += 6.0
            return super().read(min(n, 1000))

    opener = Opener(Trickle(PNG + b"0" * 40_000))
    tiles = TileCache(tmp_path / "tiles", 10_000_000, FakeClock(), opener, monotonic=lambda: now[0])
    assert tiles.get(OSM, 1, 0, 0) is None
    assert not list((tmp_path / "tiles").rglob("*.png"))
    assert tiles.get(OSM, 1, 1, 0) is None  # failing fast now
    assert len(opener.requests) == 1


def test_shrinking_the_cap_purges_in_the_background(tmp_path: Path) -> None:
    opener = Opener(Response(PNG))
    tiles, clock = cache(tmp_path, opener)
    for x in range(6):
        clock.advance(1000)
        tiles.get(OSM, 3, x, 0)
    tiles.wait_idle()
    assert len(list((tmp_path / "tiles").rglob("*.png"))) == 6
    tiles.set_cap(len(PNG) * 2)
    tiles.wait_idle()
    left = sorted(p.parent.name for p in (tmp_path / "tiles" / "osm" / "3").rglob("*.png"))
    assert left == ["5"]  # 90% of two tiles holds one


def test_eviction_works_in_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tile_store, "EVICT_BATCH", 2)
    store = TileStore(tmp_path / "tiles")
    for x in range(9):
        store.put("osm", "png", (3, x, 0), PNG, "image/png", 10**12, None, None, 1000 + x)
    store.evict(len(PNG) * 4, 0.9)
    left = sorted(int(p.parent.name) for p in (tmp_path / "tiles" / "osm" / "3").rglob("*.png"))
    assert left == [6, 7, 8]
    assert store.total_size() == len(PNG) * 3


def test_a_locked_index_never_fails_a_cache_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tile_store, "BUSY_TIMEOUT_S", 0.05)
    opener = Opener(Response(PNG))
    tiles, _ = cache(tmp_path, opener)
    tiles.get(OSM, 1, 0, 0)
    tiles.wait_idle()
    blocker = sqlite3.connect(tmp_path / "tiles" / "index.sqlite3")
    blocker.execute("BEGIN IMMEDIATE")
    try:
        assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    finally:
        blocker.rollback()
        blocker.close()


def test_a_damaged_index_is_recreated(tmp_path: Path) -> None:
    opener = Opener(Response(PNG))
    tiles, _ = cache(tmp_path, opener)
    (tmp_path / "tiles").mkdir(parents=True)
    (tmp_path / "tiles" / "index.sqlite3").write_bytes(b"this is not a database" * 50)
    assert tiles.get(OSM, 1, 0, 0) == (PNG, "image/png")
    tiles.get(OSM, 1, 0, 0)
    assert len(opener.requests) == 1  # the new index remembered it


def test_an_index_number_that_cannot_be_stored_is_a_miss_not_an_error(tmp_path: Path) -> None:
    store = TileStore(tmp_path / "tiles")
    store.put("osm", "png", (1, 0, 0), PNG, "image/png", 2**70, None, None, 1)
    assert store.row("osm", 1, 0, 0) is None


def test_a_huge_max_age_or_expires_is_clamped_to_30_days(tmp_path: Path) -> None:
    opener = Opener(
        Response(PNG, Cache_Control="max-age=99999999999999999999"),
        Response(PNG, Expires="Fri, 31 Dec 9999 23:59:59 GMT"),
        Response(PNG),
        Response(PNG),
    )
    tiles, clock = cache(tmp_path, opener)
    tiles.get(EOX, 1, 0, 0)
    tiles.get(EOX, 1, 1, 0)
    clock.advance(29 * DAY_MS)
    tiles.get(EOX, 1, 0, 0)
    tiles.get(EOX, 1, 1, 0)
    assert len(opener.requests) == 2
    clock.advance(2 * DAY_MS)
    tiles.get(EOX, 1, 0, 0)
    assert len(opener.requests) == 3
