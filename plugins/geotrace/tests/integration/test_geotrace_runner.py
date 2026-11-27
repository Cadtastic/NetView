from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from netview_local_plugins.geotrace.changes import ChangeTracker
from netview_local_plugins.geotrace.geo import Location
from netview_local_plugins.geotrace.model import Target
from netview_local_plugins.geotrace.placement import Home
from netview_local_plugins.geotrace.runner import Job, LiveTrace, TraceRunner
from netview_local_plugins.geotrace.storage import TargetStore, TraceStore, storage_spec

from netview.application.plugins.context import PluginIdentity
from netview.infrastructure.db.engine import make_plugin_engine, plugin_data_file
from netview.infrastructure.db.migrate import upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk import EventKind, PingResult, TraceHop, TraceResult
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeCore,
    FakeNetworkTools,
    FakePluginContext,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
    RecordingEventBus,
)

GUID = "f64f43b1-9ff2-47b9-badf-390b2fef25db"
IP = "8.8.8.8"


class FakeLocator:
    def locate(self, ip: str) -> Location | None:
        if ip == IP:
            return Location("Mountain View", "CA", "US", 37.4, -122.1, 15169, "Google")
        return None


class SeqNet(FakeNetworkTools):
    """Answers pings from a list (None = lost) and counts the calls."""

    def __init__(
        self,
        traces: dict[str, TraceResult],
        seq: list[float | None],
        hop_spy: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(traces=traces)
        self.seq = seq
        self.pings = 0
        self.trace_calls = 0
        self.hop_spy = hop_spy

    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
        self.pings += 1
        value = self.seq.pop(0) if self.seq else None
        return None if value is None else PingResult(value, 57)

    def traceroute(
        self, ip: str, max_hops: int = 30, probe_timeout_ms: int = 1000, on_hop: Any = None
    ) -> TraceResult:
        self.trace_calls += 1

        def spied(hop: TraceHop) -> None:
            on_hop(hop)
            if self.hop_spy is not None:
                self.hop_spy()

        return super().traceroute(ip, max_hops, probe_timeout_ms, spied if on_hop else None)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[tuple[TargetStore, TraceStore]]:
    data_file = plugin_data_file(tmp_path, GUID)
    engine = make_plugin_engine(data_file)
    upgrade_plugin(engine, storage_spec().versions_dir)
    engine.dispose()
    ctx = DefaultPluginContext(
        PluginIdentity(GUID, 1, "GeoTrace", data_file), None, data_file, FakeClock(), FakeNetworkTools(),
        FakeVendors(), InMemoryMetrics(), None,  # type: ignore[arg-type]
        RecordingEventBus(), FakeServiceProbes(), FakeSystemInfo(), FakeSnmpClient([]),
    )  # fmt: skip
    yield TargetStore(ctx.unit_of_work), TraceStore(ctx.unit_of_work)
    ctx.close()


def _hops() -> tuple[TraceHop, ...]:
    return (TraceHop(1, "192.168.1.1", (0.5, 0.5, 0.5)), TraceHop(2, IP, (12.0, 12.5, 13.0)))


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        db: tuple[TargetStore, TraceStore],
        traces: dict[str, TraceResult] | None = None,
        replies: list[float | None] | None = None,
        getaddrinfo: Callable[..., Any] = socket.getaddrinfo,
    ) -> None:
        self.core = FakeCore()
        self.ctx = FakePluginContext(None, snmp=None, core=self.core, files_dir=tmp_path)
        self.net = SeqNet(
            traces if traces is not None else {IP: TraceResult(IP, _hops(), True, None)},
            list(replies if replies is not None else [10.0, 12.0] + [11.0] * 8),
        )
        self.ctx.net = self.net  # type: ignore[assignment]
        self.sleeps: list[float] = []
        self.locator_calls = 0
        self.targets, self.traces = db

        def locator_fn() -> FakeLocator:
            self.locator_calls += 1
            return FakeLocator()

        self.runner = TraceRunner(
            self.ctx, self.traces, ChangeTracker(), lambda: Home(40.0, -111.0, "home"), locator_fn,
            sleep=self.sleeps.append, getaddrinfo=getaddrinfo,
        )  # fmt: skip


def _job(**kw: Any) -> Job:
    base: dict[str, Any] = {
        "target_id": None, "address": IP, "family": "ipv4", "trigger": "manual",
        "mode": "trace", "name": "dns",
    }  # fmt: skip
    base.update(kw)
    return Job(**base)


def _live() -> LiveTrace:
    return LiveTrace(id=-1, started_ms=1_800_000_000_000)


def test_done_trace_saved_with_resolved_ip_and_ping_stats(
    tmp_path: Path, db: tuple[TargetStore, TraceStore]
) -> None:
    rig = Rig(tmp_path, db)
    live = _live()
    trace = rig.runner.run(_job(), live)
    assert trace.status == "done" and trace.reached and trace.error is None
    assert trace.resolved_ip == IP
    assert trace.id > 0 and rig.traces.get(trace.id) == trace
    assert trace.hop_count == 2 and trace.hops[1].city == "Mountain View"
    assert trace.loss_pct == 0.0
    assert trace.rtt_ms == pytest.approx(11.0)
    assert (trace.ping_min_ms, trace.ping_max_ms) == (10.0, 12.0)
    assert trace.jitter_ms == pytest.approx(3 / 9)  # consecutive differences 2, 1, then seven zeros
    assert rig.sleeps == [0.2] * 9
    assert rig.locator_calls == 1
    snap = live.snapshot()
    assert snap.status == "done" and len(snap.hops) == 2


def test_hops_appear_in_live_during_traceroute(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    rig = Rig(tmp_path, db)
    live = _live()
    seen: list[int] = []
    rig.net.hop_spy = lambda: seen.append(len(live.hops))
    rig.runner.run(_job(), live)
    assert seen == [1, 2]


def test_no_ipv6_address_is_a_failed_trace(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    def getaddrinfo(host: str, port: Any, family: int = 0, *a: Any) -> list[Any]:
        if family == socket.AF_INET6:
            raise socket.gaierror(getattr(socket, "EAI_NONAME", 8), "no data")
        return [(socket.AF_INET, 1, 6, "", (IP, 0))]

    rig = Rig(tmp_path, db, getaddrinfo=getaddrinfo)
    trace = rig.runner.run(_job(address="example.test", family="ipv6"), _live())
    assert trace.status == "failed" and trace.error == "example.test has no IPv6 address"
    assert trace.resolved_ip is None and trace.hops == ()
    assert rig.traces.get(trace.id) == trace
    assert rig.net.trace_calls == 0 and rig.net.pings == 0


def test_traceroute_error_is_a_failed_trace(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    rig = Rig(tmp_path, db, traces={})
    trace = rig.runner.run(_job(), _live())
    assert trace.status == "failed" and trace.error == "traceroute is not installed"
    assert trace.resolved_ip == IP


def test_ping_only_skips_traceroute(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    rig = Rig(tmp_path, db)
    trace = rig.runner.run(_job(mode="ping"), _live())
    assert rig.net.trace_calls == 0
    assert trace.status == "done" and trace.reached and trace.hops == () and trace.signature == "[]"
    assert trace.rtt_ms is not None


def test_once_trace_raises_no_events(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    rig = Rig(tmp_path, db, traces={})
    for _ in range(4):
        rig.runner.run(_job(trigger="once", target_id=None), _live())
    assert rig.core.events == []


def test_scheduled_failures_raise_unreachable_event_with_ip(
    tmp_path: Path, db: tuple[TargetStore, TraceStore]
) -> None:
    rig = Rig(tmp_path, db, traces={})
    t: Target = rig.targets.add("dns", IP, "ipv4", 15, True, 1000)
    for _ in range(3):
        rig.runner.run(_job(trigger="scheduled", target_id=t.id), _live())
    assert rig.core.events == [(EventKind.PLUGIN, "GeoTrace · dns: unreachable (3 traces in a row)", IP)]


def test_all_pings_lost(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    rig = Rig(tmp_path, db, replies=[None] * 10)
    trace = rig.runner.run(_job(), _live())
    assert trace.loss_pct == 100.0
    assert trace.rtt_ms is None and trace.jitter_ms is None
    assert trace.ping_min_ms is None and trace.ping_max_ms is None
    assert trace.status == "done"


def test_partial_loss(tmp_path: Path, db: tuple[TargetStore, TraceStore]) -> None:
    rig = Rig(tmp_path, db, replies=[10.0, None, 20.0] + [None] * 7)
    trace = rig.runner.run(_job(), _live())
    assert trace.loss_pct == 80.0
    assert trace.rtt_ms == 15.0 and trace.jitter_ms == 10.0
