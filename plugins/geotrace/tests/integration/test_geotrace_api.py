"""The GeoTrace API through NetView's real app: routes, the core's guard, errors and audit."""

from __future__ import annotations

import io
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from netview_local_plugins.geotrace import plugin as plugin_module
from netview_local_plugins.geotrace.changes import signature_json
from netview_local_plugins.geotrace.geocode import GeocodeError, Geocoder
from netview_local_plugins.geotrace.geodata import GeoData
from netview_local_plugins.geotrace.model import Hop, Trace
from netview_local_plugins.geotrace.service import GeoTraceService

from netview.application.ports.audit import AuditEntry
from netview.infrastructure.settings import AppSettings
from netview.sdk import PingResult, TraceHop, TraceResult
from netview.sdk.testing.addresses import api_base
from netview.sdk.testing.auth import admin_cookies
from netview.sdk.testing.fakes import FakeNetworkTools, FakeServiceProbes

PLUGINS_DIR = Path(__file__).resolve().parents[3]
GUID = "f64f43b1-9ff2-47b9-badf-390b2fef25db"
IP = "8.8.8.8"
HOUR = 3_600_000
DAY = 24 * HOUR


def _now() -> int:
    return int(time.time() * 1000)


class Net(FakeNetworkTools):
    def __init__(self) -> None:
        hops = (TraceHop(1, "192.168.1.1", (1.0,)), TraceHop(2, IP, (9.0,)))
        super().__init__(traces={IP: TraceResult(IP, hops, True, None)})

    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
        return PingResult(9.0, 57) if ip == IP else None


class Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class Rig:
    def __init__(self, client: TestClient, base: str, service: GeoTraceService, audit: Audit) -> None:
        self.client = client
        self.base = base
        self.service = service
        self.audit = audit

    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get(f"{self.base}{path}", **kw)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"{self.base}{path}", json=body)

    def put(self, path: str, body: Any) -> Any:
        return self.client.put(f"{self.base}{path}", json=body)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"{self.base}{path}")

    def add(self, name: str = "dns", address: str = IP, **extra: Any) -> dict[str, Any]:
        response = self.post("/targets", {"name": name, "address": address, **extra})
        assert response.status_code == 201, response.text
        return dict(response.json())

    def wait_done(self, trace_id: int, seconds: float = 10.0) -> dict[str, Any]:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            body = self.get(f"/traces/{trace_id}").json()
            if body["status"] in ("done", "failed"):
                return dict(body)
            time.sleep(0.02)
        raise AssertionError("trace did not finish")

    def save(self, target_id: int | None, started_ms: int, signature: str = "[]", **changes: Any) -> int:
        trace = Trace(
            0, target_id, "scheduled", "trace", "done", None, started_ms, started_ms + 5, IP, "ipv4", True,
            0, 10.0, 0.0, 0.0, 9.0, 11.0, signature, (),
        )  # fmt: skip
        return self.service.traces.save(replace(trace, **changes))

    def save_route(self, target_id: int, started_ms: int, hops: list[Hop]) -> int:
        return self.save(target_id, started_ms, signature_json(hops), hops=tuple(hops), hop_count=len(hops))


def hop(n: int, city: str, asn: int | None, placement: str = "located") -> Hop:
    located = placement == "located"
    return Hop(
        n, f"10.0.0.{n}", (float(n),), city, "", "", 1.0 if located else None, 2.0 if located else None,
        asn, "", placement, True,
    )  # fmt: skip


@pytest.fixture
def make(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plugin_seeds: Callable[..., dict[str, Any]]
) -> Iterator[Callable[..., Rig]]:
    clients: list[TestClient] = []
    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: Net())
    monkeypatch.setattr("netview.bootstrap.SystemServiceProbes", lambda **kw: FakeServiceProbes())
    built: list[GeoTraceService] = []
    audit = Audit()

    def factory(ctx: Any, settings: Any, *a: Any, **kw: Any) -> GeoTraceService:
        ctx._audit_sink = audit
        service = GeoTraceService(ctx, settings, *a, sleep=lambda _: None, **kw)
        built.append(service)
        return service

    monkeypatch.setattr(plugin_module, "GeoTraceService", factory)

    def build(seed: dict[str, Any] | None = None) -> Rig:
        from netview.bootstrap import create_application

        seeds = plugin_seeds()
        seeds[GUID] = {**seeds[GUID], **(seed or {})}  # the quiet defaults first, the test's own over them
        app = create_application(
            AppSettings(
                data_dir=tmp_path,
                subnet="192.168.1.0/24",
                plugins=seeds,
                plugin_dirs=[PLUGINS_DIR],
            )
        )
        client = TestClient(
            app,
            base_url="http://localhost",
            headers={"X-Netview": "1"},
            cookies=admin_cookies(app.state.services),
        )
        client.__enter__()
        clients.append(client)
        return Rig(client, api_base(app.state.services, GUID), built[-1], audit)

    yield build
    for c in clients:
        c.__exit__(None, None, None)


# -- targets -------------------------------------------------------------------------------------


def test_crud_round_trip(make: Callable[..., Rig]) -> None:
    rig = make()
    assert rig.get("/targets").json() == []
    created = rig.add("Google DNS")
    assert created["name"] == "Google DNS"
    assert (created["family"], created["interval_min"], created["enabled"]) == ("ipv4", 15, True)
    listed = rig.get("/targets").json()
    assert [t["id"] for t in listed] == [created["id"]]
    assert listed[0]["last"] is None
    edited = rig.put(f"/targets/{created['id']}", {"name": "DNS", "interval_min": 30})
    assert edited.status_code == 200
    assert (edited.json()["name"], edited.json()["interval_min"], edited.json()["address"]) == ("DNS", 30, IP)
    assert rig.delete(f"/targets/{created['id']}").status_code == 204
    assert rig.get("/targets").json() == []
    assert rig.delete(f"/targets/{created['id']}").status_code == 404
    assert rig.put(f"/targets/{created['id']}", {"name": "x"}).status_code == 404


def test_new_target_takes_settings_defaults_and_an_ip_literal_sets_its_family(
    make: Callable[..., Rig],
) -> None:
    rig = make({"default_interval_min": 60, "default_family": "ipv6"})
    named = rig.add("site", "example.com")
    assert (named["family"], named["interval_min"]) == ("ipv6", 60)
    assert rig.add("v4", IP)["family"] == "ipv4"
    assert rig.add("v6", "2001:4860:4860::8888", family="ipv4")["family"] == "ipv6"


def test_the_51st_target_is_422(make: Callable[..., Rig]) -> None:
    rig = make()
    for i in range(50):
        rig.add(f"t{i}", f"host{i}.example.com")
    response = rig.post("/targets", {"name": "more", "address": "more.example.com"})
    assert response.status_code == 422
    assert response.json() == {"error": "at most 50 targets"}


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "address": "https://netflix.com/"},
        {"name": "x", "address": ""},
        {"name": "x"},
        {"address": IP},
        {"name": "", "address": IP},
        {"name": "x", "address": IP, "family": "ipx"},
        {"name": "x", "address": IP, "interval_min": 7},
        {"name": "x", "address": IP, "interval_min": "15"},
        {"name": "x", "address": IP, "interval_min": True},
        {"name": "x", "address": IP, "enabled": "yes"},
        {"name": 5, "address": IP},
        ["not", "an", "object"],
    ],
)
def test_bad_target_bodies_are_422_with_a_plain_message(make: Callable[..., Rig], body: Any) -> None:
    response = make().post("/targets", body)
    assert response.status_code == 422
    assert isinstance(response.json()["error"], str) and response.json()["error"]


def test_put_validates_too(make: Callable[..., Rig]) -> None:
    rig = make()
    target = rig.add()
    for body in ({"address": "bad address"}, {"interval_min": 3}, {"enabled": 1}, {"family": "x"}):
        assert rig.put(f"/targets/{target['id']}", body).status_code == 422
    assert rig.get("/targets").json()[0]["address"] == IP


# -- tracing -------------------------------------------------------------------------------------


def test_trace_now_then_poll_to_done_and_the_trace_is_listed(make: Callable[..., Rig]) -> None:
    rig = make()
    target = rig.add()
    started = rig.post(f"/targets/{target['id']}/trace")
    assert started.status_code == 202
    trace_id = started.json()["trace_id"]
    done = rig.wait_done(trace_id)
    assert done["status"] == "done" and done["reached"] is True
    assert [h["n"] for h in done["hops"]] == [1, 2]
    assert done["hops"][1]["ip"] == IP
    saved = rig.get(f"/traces/{trace_id}").json()
    assert saved["id"] > 0 and saved["target_id"] == target["id"]
    summaries = rig.get(f"/targets/{target['id']}/traces").json()
    assert [s["id"] for s in summaries] == [saved["id"]]
    assert "hops" not in summaries[0]
    row = rig.get("/targets").json()[0]
    assert row["last"]["trace_id"] == saved["id"] and row["last"]["status"] == "done"
    assert row["last"]["hop_count"] == 2 and row["last"]["loss_pct"] == 0.0
    assert rig.get(f"/traces/{saved['id']}").json()["hops"][0]["ip"] == "192.168.1.1"


def test_unknown_targets_are_404(make: Callable[..., Rig]) -> None:
    rig = make()
    assert rig.post("/targets/99/trace").status_code == 404
    assert rig.get("/targets/99/traces").status_code == 404
    assert rig.get("/targets/99/compare").status_code == 404
    assert rig.get("/targets/99/trends?range=7d").status_code == 404


def test_trace_once_runs_and_is_audited(make: Callable[..., Rig]) -> None:
    rig = make()
    started = rig.post("/trace-once", {"address": IP, "family": "ipv4", "mode": "ping"})
    assert started.status_code == 202
    done = rig.wait_done(started.json()["trace_id"])
    assert done["mode"] == "ping" and done["status"] == "done"
    assert [(e.action, e.target) for e in rig.audit.entries] == [("geotrace.trace_once", IP)]


@pytest.mark.parametrize(
    "body",
    [
        {"address": "https://x.com", "family": "ipv4", "mode": "trace"},
        {"address": IP, "family": "ipv5", "mode": "trace"},
        {"address": IP, "family": "ipv4", "mode": "scan"},
        {"family": "ipv4", "mode": "trace"},
    ],
)
def test_bad_trace_once_bodies_are_422(make: Callable[..., Rig], body: dict[str, Any]) -> None:
    assert make().post("/trace-once", body).status_code == 422


def test_unsaved_run_serves_the_live_snapshot_and_id_zero_is_never_looked_up(
    make: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make()

    def broken_save(trace: Trace) -> int:
        raise RuntimeError("disk")

    monkeypatch.setattr(rig.service.traces, "save", broken_save)
    started = rig.post("/trace-once", {"address": IP, "family": "ipv4", "mode": "trace"})
    body = rig.wait_done(started.json()["trace_id"])
    assert body["status"] == "failed" and body["id"] <= 0
    assert rig.get("/traces/0").status_code == 404
    assert rig.get("/traces/-99999").status_code == 404
    assert rig.get("/traces/not-a-number").status_code == 422


def test_unknown_saved_trace_is_404(make: Callable[..., Rig]) -> None:
    assert make().get("/traces/12345").status_code == 404


def test_shutting_down_is_503(make: Callable[..., Rig]) -> None:
    rig = make()
    target = rig.add()
    rig.service.queue.close()
    response = rig.post(f"/targets/{target['id']}/trace")
    assert response.status_code == 503
    assert response.json() == {"error": "GeoTrace is shutting down"}
    assert rig.post("/trace-once", {"address": IP, "family": "ipv4", "mode": "trace"}).status_code == 503


def test_traces_page_newest_first_with_before_and_limit(make: Callable[..., Rig]) -> None:
    rig = make()
    target = rig.add()
    ids = [rig.save(target["id"], 1000 + i) for i in range(5)]
    listed = rig.get(f"/targets/{target['id']}/traces?limit=2").json()
    assert [t["id"] for t in listed] == [ids[4], ids[3]]
    older = rig.get(f"/targets/{target['id']}/traces?before_ms=1003&limit=50").json()
    assert [t["id"] for t in older] == [ids[2], ids[1], ids[0]]
    assert len(rig.get(f"/targets/{target['id']}/traces?limit=9999").json()) == 5


# -- compare -------------------------------------------------------------------------------------


def test_compare_aligns_rows_by_hop_number_and_finds_the_split(make: Callable[..., Rig]) -> None:
    rig = make()
    tid = rig.add()["id"]
    old = [hop(1, "Home", 1), hop(2, "Salt Lake City", 2), hop(3, "Salt Lake City", 2), hop(4, "Dallas", 3)]
    new = [
        hop(1, "Home", 1), hop(2, "Salt Lake City", 2), hop(3, "Denver", 5), hop(4, "Dallas", 3),
        hop(5, "Austin", 3),
    ]  # fmt: skip
    first = rig.save_route(tid, 1000, old)
    second = rig.save_route(tid, 2000, new)
    body = rig.get(f"/targets/{tid}/compare").json()  # a = newest, b = newest with a different route
    assert body["a"]["id"] == second and body["b"]["id"] == first
    assert [r["n"] for r in body["rows"]] == [1, 2, 3, 4, 5]
    assert [r["differs"] for r in body["rows"]] == [False, False, True, False, True]
    assert body["rows"][4]["b"] is None and body["rows"][4]["a"]["city"] == "Austin"
    assert body["split_after"] == 2
    assert "hops" not in body["a"]


def test_compare_explicit_ids_and_identical_routes(make: Callable[..., Rig]) -> None:
    rig = make()
    tid = rig.add()["id"]
    route = [hop(1, "Home", 1), hop(2, "Dallas", 3)]
    first = rig.save_route(tid, 1000, route)
    second = rig.save_route(tid, 2000, route)
    body = rig.get(f"/targets/{tid}/compare?a={first}&b={second}").json()
    assert body["split_after"] is None and not any(r["differs"] for r in body["rows"])
    default = rig.get(f"/targets/{tid}/compare").json()  # same route twice: b is the previous trace
    assert (default["a"]["id"], default["b"]["id"]) == (second, first)


def test_compare_silent_hop_differs_only_when_the_other_side_is_located(make: Callable[..., Rig]) -> None:
    rig = make()
    tid = rig.add()["id"]
    a = rig.save_route(tid, 1000, [hop(1, "Home", 1), hop(2, "", None, "none"), hop(3, "", None, "none")])
    b = rig.save_route(tid, 2000, [hop(1, "Home", 1), hop(2, "Dallas", 3), hop(3, "", None, "none")])
    rows = rig.get(f"/targets/{tid}/compare?a={a}&b={b}").json()["rows"]
    assert [r["differs"] for r in rows] == [False, True, False]


def test_compare_needs_two_traces_of_this_target(make: Callable[..., Rig]) -> None:
    rig = make()
    tid = rig.add()["id"]
    other = rig.add("other", "1.1.1.1")["id"]
    assert rig.get(f"/targets/{tid}/compare").status_code == 404
    only = rig.save_route(tid, 1000, [hop(1, "Home", 1)])
    assert rig.get(f"/targets/{tid}/compare").status_code == 404
    foreign = rig.save_route(other, 1000, [hop(1, "Home", 1)])
    assert rig.get(f"/targets/{tid}/compare?a={only}&b={foreign}").status_code == 404


# -- trends --------------------------------------------------------------------------------------


def test_trends_ranges(make: Callable[..., Rig]) -> None:
    rig = make()
    tid = rig.add()["id"]
    now = _now()
    rig.save(tid, now - HOUR, '[[1, "A"]]', rtt_ms=12.0)
    rig.save(tid, now - 40 * DAY, "[]", rtt_ms=99.0)
    day = rig.get(f"/targets/{tid}/trends?range=24h").json()
    assert set(day) == {"rtt", "hops", "loss", "changes"}
    assert len(day["rtt"]) == 96
    assert [v for _, v in day["rtt"] if v is not None] == [12.0]
    long = rig.get(f"/targets/{tid}/trends?range=90d").json()
    assert sorted(v for _, v in long["rtt"] if v is not None) == [12.0, 99.0]
    assert rig.get(f"/targets/{tid}/trends?range=1y").status_code == 422
    assert rig.get(f"/targets/{tid}/trends").status_code == 200  # default range


# -- note ----------------------------------------------------------------------------------------


def test_note_says_how_long_the_route_has_been_steady_or_when_it_changed(make: Callable[..., Rig]) -> None:
    rig = make()
    steady = rig.add("steady", "1.1.1.1")["id"]
    changed = rig.add("changed", "1.0.0.1")["id"]
    quiet = rig.add("quiet", "9.9.9.9")["id"]
    lonely = rig.add("lonely", "9.9.9.8")["id"]
    now = _now()
    a, b = '[[1, "A"]]', '[[1, "B"]]'
    for i in range(4):
        rig.save(steady, now - 2 * DAY - 10 * 60_000 + i * HOUR, a)
    for t, sig in (
        (now - 10 * HOUR, a),
        (now - 4 * HOUR, a),
        (now - 3 * HOUR - 5 * 60_000, b),
        (now - HOUR, b),
    ):
        rig.save(changed, t, sig)
    rig.save(quiet, now - HOUR, "[]")
    rig.save(lonely, now - HOUR, a)
    notes = {t["id"]: t["note"] for t in rig.get("/targets").json()}
    assert notes[steady] == "steady 2 days"
    assert notes[changed] == "route changed 3 h ago"
    assert notes[quiet] == ""
    assert notes[lonely] == ""


# -- status --------------------------------------------------------------------------------------


def test_status_reports_geo_home_and_traceroute(make: Callable[..., Rig]) -> None:
    rig = make()
    status = rig.get("/status").json()
    assert set(status["geo"]) == {"city", "asn", "last_error", "checked_ms"}
    assert status["home_set"] is False and status["traceroute_ok"] is True
    rig.save(None, 5000, status="failed", error="traceroute is not installed", reached=False)
    assert rig.get("/status").json()["traceroute_ok"] is False
    rig.save(None, 6000, status="failed", error="cannot find x", reached=False)
    assert rig.get("/status").json()["traceroute_ok"] is True


def test_home_set_follows_the_settings(make: Callable[..., Rig]) -> None:
    rig = make({"home_lat": 40.0, "home_lon": -111.0})
    assert rig.get("/status").json()["home_set"] is True


def test_first_status_call_starts_the_geo_download_once_and_without_blocking(
    make: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def ensure(self: GeoData) -> None:
        calls.append(1)
        started.set()
        release.wait(10)

    monkeypatch.setattr(GeoData, "ensure", ensure)
    monkeypatch.setattr(GeoData, "update", lambda self, force=False: None)
    rig = make({"geo_auto_update": True})
    try:
        assert rig.get("/status").status_code == 200  # returned while ensure() is still blocked
        assert started.wait(5)
        rig.get("/status")
        rig.get("/status")
        assert calls == [1]
    finally:
        release.set()


def test_status_does_not_download_when_auto_update_is_off(
    make: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(GeoData, "ensure", lambda self: calls.append(1))
    rig = make()
    rig.get("/status")
    time.sleep(0.1)
    assert calls == []


# -- audit ---------------------------------------------------------------------------------------


def test_target_changes_are_audited_with_the_address(make: Callable[..., Rig]) -> None:
    rig = make()
    target = rig.add("a", IP)
    rig.put(f"/targets/{target['id']}", {"address": "1.1.1.1"})
    rig.delete(f"/targets/{target['id']}")
    assert [(e.action, e.target) for e in rig.audit.entries] == [
        ("geotrace.target.add", IP),
        ("geotrace.target.edit", "1.1.1.1"),
        ("geotrace.target.delete", "1.1.1.1"),
    ]


def test_a_refused_change_is_not_audited(make: Callable[..., Rig]) -> None:
    rig = make()
    rig.post("/targets", {"name": "x", "address": "https://bad/"})
    rig.delete("/targets/77")
    assert rig.audit.entries == []


# -- geocode -------------------------------------------------------------------------------------

NOMINATIM = [
    {"display_name": "Salt Lake City, Utah, United States", "lat": "40.7596", "lon": "-111.8868"},
    {"display_name": "Salt Lake County, Utah", "lat": "40.66", "lon": "-111.9"},
    {"nonsense": True},
]


class Opener:
    def __init__(self, payload: Any = NOMINATIM, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float = 0) -> Any:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return io.BytesIO(json.dumps(self.payload).encode())


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _geocoder(opener: Opener, clock: Clock) -> Geocoder:
    return Geocoder(opener, monotonic=clock.monotonic, sleep=clock.sleep)


def test_geocoder_asks_nominatim_with_our_user_agent() -> None:
    opener, clock = Opener(), Clock()
    results = _geocoder(opener, clock).search("Salt Lake")
    assert results == [
        {"label": "Salt Lake City, Utah, United States", "lat": 40.7596, "lon": -111.8868},
        {"label": "Salt Lake County, Utah", "lat": 40.66, "lon": -111.9},
    ]
    request = opener.requests[0]
    assert (
        request.full_url == "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q=Salt%20Lake"
    )
    assert (
        request.get_header("User-agent") == "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
    )


def test_geocoder_serves_a_repeat_from_cache_within_the_hour_then_asks_again() -> None:
    opener, clock = Opener(), Clock()
    geocoder = _geocoder(opener, clock)
    geocoder.search("Salt Lake")
    clock.now += 0.2
    geocoder.search("  salt lake ")
    assert len(opener.requests) == 1 and clock.slept == []
    clock.now += 3601
    geocoder.search("Salt Lake")
    assert len(opener.requests) == 2


def test_geocoder_waits_so_requests_are_a_second_apart() -> None:
    opener, clock = Opener(), Clock()
    geocoder = _geocoder(opener, clock)
    geocoder.search("one")
    clock.now += 0.25
    geocoder.search("two")
    assert len(opener.requests) == 2
    assert clock.slept == [pytest.approx(0.75)]
    clock.now += 5
    geocoder.search("three")
    assert clock.slept == [pytest.approx(0.75)]  # no wait needed after a long gap


def test_geocoder_failures_raise_and_are_not_cached() -> None:
    clock = Clock()
    for error in (OSError("down"), TimeoutError("slow"), ValueError("bad")):
        with pytest.raises(GeocodeError):
            _geocoder(Opener(error=error), clock).search("x")
    with pytest.raises(GeocodeError):
        _geocoder(Opener(payload={"not": "a list"}), clock).search("x")
    opener = Opener(error=OSError("down"))
    geocoder = _geocoder(opener, clock)
    with pytest.raises(GeocodeError):
        geocoder.search("y")
    opener.error = None
    assert geocoder.search("y")


def test_geocode_route_validates_and_maps_failures(
    make: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = Opener()
    monkeypatch.setattr(plugin_module, "default_opener", opener)
    rig = make()
    ok = rig.get("/geocode", params={"q": "Salt Lake"})
    assert ok.status_code == 200 and ok.json()[0]["label"].startswith("Salt Lake City")
    assert rig.get("/geocode", params={"q": "Salt Lake"}).status_code == 200
    assert len(opener.requests) == 1  # the repeat came from the cache
    for q in ("", "   ", "x" * 201):
        assert rig.get("/geocode", params={"q": q}).status_code == 422
    assert rig.get("/geocode").status_code == 422
    opener.error = OSError("offline")
    down = rig.get("/geocode", params={"q": "Elsewhere"})
    assert down.status_code == 502
    assert down.json() == {"error": "address search is unavailable"}


# -- the core's guard ----------------------------------------------------------------------------


def test_the_core_guard_applies_to_every_route(make: Callable[..., Rig]) -> None:
    rig = make()
    anonymous = TestClient(rig.client.app, base_url="http://localhost", headers={"X-Netview": "1"})
    assert anonymous.get(f"{rig.base}/targets").status_code in (401, 403)
    assert anonymous.post(f"{rig.base}/targets", json={"name": "x", "address": IP}).status_code in (401, 403)
