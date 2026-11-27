from __future__ import annotations

import io
import threading
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from netview_local_plugins.geotrace.settings import GeoTraceSettings
from netview_local_plugins.geotrace.tiles import TileCache, TileSource, sources

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
    ):
        settings = GeoTraceSettings.model_construct(
            **{**GeoTraceSettings().model_dump(), "tile_source": "custom", "custom_tile_url": bad}
        )
        assert set(sources(settings)) == {"osm", "eox-s2"}, bad


@pytest.mark.parametrize("claimed", ["osm", "eox-s2"])
def test_source_names_are_stable(claimed: str) -> None:
    assert sources(GeoTraceSettings())[claimed].name == claimed
