from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from netview_local_plugins.geotrace.model import Trace
from netview_local_plugins.geotrace.runner import Job
from netview_local_plugins.geotrace.service import GeoTraceService, TargetLimitError
from netview_local_plugins.geotrace.settings import GeoTraceSettings
from netview_local_plugins.geotrace.storage import storage_spec

from netview.application.plugins.context import PluginIdentity
from netview.infrastructure.db.engine import make_plugin_engine, plugin_data_file
from netview.infrastructure.db.migrate import upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk import PingResult, TraceHop, TraceResult
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
DAY = 86_400_000


class GateNet(FakeNetworkTools):
    """Traceroute waits on ``gate`` (when closed) and tells the test when it has started."""

    def __init__(self) -> None:
        super().__init__(traces={IP: TraceResult(IP, (TraceHop(1, IP, (5.0, 5.0, 5.0)),), True, None)})
        self.gate = threading.Event()
        self.gate.set()
        self.entered = threading.Event()
        self.calls = 0
        self.pings = 0

    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
        self.pings += 1
        return PingResult(5.0, 57)

    def traceroute(
        self, ip: str, max_hops: int = 30, probe_timeout_ms: int = 1000, on_hop: Any = None
    ) -> TraceResult:
        self.calls += 1
        self.entered.set()
        self.gate.wait(10)
        return super().traceroute(ip, max_hops, probe_timeout_ms, on_hop)


class SpyGeo:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ensure(self) -> None:
        self.calls.append("ensure")

    def update(self, force: bool = False) -> None:
        self.calls.append(f"update:{force}")

    def locator(self) -> None:
        return None

    def cancel(self) -> None:
        self.calls.append("cancel")

    def stop(self, timeout_s: float) -> bool:
        self.calls.append("stop")
        return True

    def close(self) -> None:
        self.calls.append("close")

    def status(self) -> dict[str, Any]:
        return {}


class SpyTracker:
    def __init__(self) -> None:
        self.seeded: dict[int, list[Trace]] = {}
        self.observed: list[Trace] = []
        self.forgotten: list[int] = []
        self.rebaselined = 0

    def rebaseline_all(self) -> None:
        self.rebaselined += 1

    def seed(self, target_id: int, traces: Any) -> None:
        self.seeded[target_id] = list(traces)

    def forget(self, target_id: int) -> None:
        self.forgotten.append(target_id)

    def observe(self, target: Any, trace: Trace, recent: Any) -> list[str]:
        self.observed.append(trace)
        return []


def _worker_alive() -> bool:
    return any(t.name == "geotrace-worker" for t in threading.enumerate())


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        data_file = plugin_data_file(tmp_path, GUID)
        engine = make_plugin_engine(data_file)
        upgrade_plugin(engine, storage_spec().versions_dir)
        engine.dispose()
        self.clock = FakeClock()
        self.default = DefaultPluginContext(
            PluginIdentity(GUID, 1, "GeoTrace", data_file), None, data_file, self.clock, FakeNetworkTools(),
            FakeVendors(), InMemoryMetrics(), None,  # type: ignore[arg-type]
            RecordingEventBus(), FakeServiceProbes(), FakeSystemInfo(), FakeSnmpClient([]),
        )  # fmt: skip
        self.core = FakeCore()
        self.settings = GeoTraceSettings(home_lat=40.0, home_lon=-111.0, home_label="home")
        self.ctx = FakePluginContext(
            self.settings, snmp=None, core=self.core, uow_factory=self.default.unit_of_work,
            clock=self.clock, files_dir=tmp_path,
        )  # fmt: skip
        self.net = GateNet()
        self.ctx.net = self.net  # type: ignore[assignment]
        self.geo = SpyGeo()
        self.tracker = SpyTracker()
        self.service = GeoTraceService(
            self.ctx,
            self.settings,
            geo=self.geo,
            tracker=self.tracker,
            sleep=lambda _: None,  # type: ignore[arg-type]
        )

    def add(self, name: str = "dns", address: str = IP, enabled: bool = True) -> int:
        return self.service.add_target(name, address, "ipv4", 15, enabled).id

    def base_trace(self, target_id: int | None, **changes: Any) -> Trace:
        trace = Trace(
            0, target_id, "scheduled", "trace", "done", None, 1, 2, IP, "ipv4", True, 0,
            5.0, 0.0, 0.0, 5.0, 5.0, "[]", (),
        )  # fmt: skip
        return replace(trace, **changes)

    def wait_for(self, check: Callable[[], Any], seconds: float = 5.0) -> Any:
        deadline = time.monotonic() + seconds
        pause = threading.Event()
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            pause.wait(0.01)
        raise AssertionError("timed out")


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = Rig(tmp_path)
    yield r
    r.net.gate.set()
    r.service.stop(wait_s=2.0)
    r.default.close()


def test_a_location_data_swap_rebaselines_the_change_tracker(rig: Rig) -> None:
    assert rig.tracker.rebaselined == 0
    rig.geo.on_swap()  # type: ignore[attr-defined]
    assert rig.tracker.rebaselined == 1


def test_the_51st_target_is_refused(rig: Rig) -> None:
    for i in range(50):
        rig.add(f"t{i}")
    with pytest.raises(TargetLimitError, match="at most 50 targets"):
        rig.add("one too many")
    assert rig.service.targets.count() == 50


def test_trace_now_twice_returns_the_same_id_and_queues_once(rig: Rig) -> None:
    tid = rig.add()
    first = rig.service.trace_now(tid)
    assert first < 0
    assert rig.service.trace_now(tid) == first
    assert rig.service.live(first) is not None


def test_trace_now_for_an_unknown_target(rig: Rig) -> None:
    with pytest.raises(LookupError):
        rig.service.trace_now(999)


def test_trace_once_twice_returns_the_same_id(rig: Rig) -> None:
    first = rig.service.trace_once(IP, "ipv4", "trace")
    assert rig.service.trace_once(IP, "ipv4", "trace") == first
    assert rig.service.trace_once(IP, "ipv4", "ping") != first


def test_tick_enqueues_due_enabled_targets_only(rig: Rig) -> None:
    on = rig.add("on")
    off = rig.add("off", enabled=False)
    rig.clock.advance(DAY)
    rig.service.tick()
    first = rig.service.queue.running_for(on)
    assert first is not None
    assert rig.service.queue.running_for(off) is None
    rig.service.tick()  # still queued: not queued twice
    assert rig.service.queue.running_for(on) == first


def test_tick_does_not_requeue_a_target_whose_save_failed(rig: Rig) -> None:
    tid = rig.add()
    rig.clock.advance(DAY)
    rig.service.tick()
    pid = rig.service.queue.running_for(tid)
    assert pid is not None
    rig.service.queue.get(0.1)
    rig.service.queue.finish(pid, 0)  # nothing stored
    rig.service.tick()
    assert rig.service.queue.running_for(tid) is None  # not due again for an interval


def test_the_worker_runs_a_manual_trace_and_the_provisional_id_resolves(rig: Rig) -> None:
    tid = rig.add()
    rig.service.start()
    pid = rig.service.trace_now(tid)
    saved = rig.wait_for(lambda: rig.service.resolve_id(pid))
    trace = rig.service.traces.get(saved)
    assert trace is not None and trace.target_id == tid and trace.trigger == "manual"
    assert trace.status == "done" and trace.hop_count == 1


def test_a_one_off_trace_is_saved_without_a_target(rig: Rig) -> None:
    rig.service.start()
    pid = rig.service.trace_once(IP, "ipv4", "ping")
    saved = rig.wait_for(lambda: rig.service.resolve_id(pid))
    trace = rig.service.traces.get(saved)
    assert trace is not None and trace.target_id is None and trace.trigger == "once" and trace.mode == "ping"


def test_the_worker_is_a_daemon_named_geotrace_worker_and_runs_one_job_at_a_time(rig: Rig) -> None:
    a, b = rig.add("a"), rig.add("b")
    rig.net.gate.clear()
    rig.service.start()
    worker = next(t for t in threading.enumerate() if t.name == "geotrace-worker")
    assert worker.daemon
    first = rig.service.trace_now(a)
    second = rig.service.trace_now(b)
    assert rig.net.entered.wait(5)
    assert rig.net.calls == 1  # b waits behind a
    waiting = rig.service.live(second)
    assert waiting is not None and waiting.snapshot().status == "queued"
    rig.net.gate.set()
    rig.wait_for(lambda: rig.service.resolve_id(first) and rig.service.resolve_id(second))
    assert rig.net.calls == 2


def test_start_seeds_the_tracker_without_ping_traces_and_never_ensures_geodata(rig: Rig) -> None:
    tid = rig.add()
    rig.service.traces.save(rig.base_trace(tid, started_ms=1))
    rig.service.traces.save(rig.base_trace(tid, started_ms=2, mode="ping"))
    rig.service.traces.save(rig.base_trace(tid, started_ms=3, status="failed", error="x"))
    rig.service.start()
    assert [(t.started_ms, t.mode) for t in rig.tracker.seeded[tid]] == [(3, "trace"), (1, "trace")]
    assert "ensure" not in rig.geo.calls


def test_a_ping_trace_never_reaches_the_tracker(rig: Rig) -> None:
    tid = rig.add()
    rig.service.start()
    rig.service.queue.put(Job(tid, IP, "ipv4", "scheduled", "ping", "dns"))
    rig.wait_for(lambda: rig.service.traces.latest(tid, 1, status=None))
    assert rig.tracker.observed == []


def test_stop_joins_the_worker_and_closes_geodata(rig: Rig) -> None:
    rig.service.start()
    rig.service.stop()
    assert not _worker_alive()
    assert rig.geo.calls == ["cancel", "stop", "close"]
    rig.service.stop()  # twice is fine


def test_stop_gives_up_on_a_running_traceroute_after_its_wait(rig: Rig) -> None:
    tid = rig.add()
    rig.net.gate.clear()
    rig.service.start()
    rig.service.trace_now(tid)
    assert rig.net.entered.wait(5)
    started = time.monotonic()
    rig.service.stop(wait_s=0.2)
    assert time.monotonic() - started < 3
    assert _worker_alive()  # still inside traceroute
    rig.net.gate.set()
    rig.wait_for(lambda: not _worker_alive())


def test_cleanup_applies_the_retention_rule(rig: Rig) -> None:
    tid = rig.add()
    now = rig.clock.now_ms()
    old_target = rig.service.traces.save(rig.base_trace(tid, started_ms=now - 91 * DAY))
    new_target = rig.service.traces.save(rig.base_trace(tid, started_ms=now - 89 * DAY))
    once = rig.base_trace(None, trigger="once")
    old_once = rig.service.traces.save(replace(once, started_ms=now - 8 * DAY))
    new_once = rig.service.traces.save(replace(once, started_ms=now - 6 * DAY))
    rig.service.cleanup()
    assert [rig.service.traces.get(i) is None for i in (old_target, old_once)] == [True, True]
    assert [rig.service.traces.get(i) is not None for i in (new_target, new_once)] == [True, True]


def test_update_geo_calls_geodata_and_never_ensure(rig: Rig) -> None:
    rig.service.update_geo()
    assert rig.geo.calls == ["update:False"]


def test_settings_changed_moves_home(rig: Rig) -> None:
    home = rig.service.home()
    assert home is not None and home.label == "home"
    rig.service.settings_changed(GeoTraceSettings())
    assert rig.service.home() is None


def test_stop_during_a_traceroute_cuts_it_short_and_nothing_is_saved_or_raised(rig: Rig) -> None:
    tid = rig.add()
    rig.net.gate.clear()
    rig.service.start()
    pid = rig.service.trace_now(tid)
    assert rig.net.entered.wait(5)
    started = time.monotonic()
    rig.service.stop(wait_s=0.2)
    assert time.monotonic() - started < 3
    rig.net.gate.set()  # the traceroute now reports its first hop and is told to stop
    rig.wait_for(lambda: not _worker_alive())
    assert rig.service.traces.latest(tid, 5, status=None) == []
    assert rig.core.events == [] and rig.tracker.observed == []
    live = rig.service.live(pid)
    assert live is not None and live.snapshot().status == "failed"
    assert live.snapshot().error == "GeoTrace was stopped"
    assert rig.net.pings == 0


def test_trace_now_moves_a_queued_scheduled_job_to_the_front_as_manual(rig: Rig) -> None:
    ids = [rig.add(f"t{i}") for i in range(3)]
    rig.clock.advance(DAY)
    rig.service.tick()
    queued = rig.service.queue.running_for(ids[2])
    assert rig.service.trace_now(ids[2]) == queued
    rig.net.gate.set()
    rig.service.start()
    saved = rig.wait_for(lambda: rig.service.resolve_id(queued))
    trace = rig.service.traces.get(saved)
    assert trace is not None and trace.trigger == "manual"


def test_an_invalid_interval_is_refused_when_adding_or_updating(rig: Rig) -> None:
    with pytest.raises(ValueError, match="5, 15, 30 or 60"):
        rig.service.add_target("x", IP, "ipv4", 7, True)
    tid = rig.add()
    with pytest.raises(ValueError, match="5, 15, 30 or 60"):
        rig.service.update_target(tid, interval_min=0)
    updated = rig.service.update_target(tid, interval_min=30, name="renamed")
    assert updated is not None and updated.interval_min == 30 and updated.name == "renamed"
    assert rig.service.update_target(999, name="x") is None


def test_tick_skips_a_target_with_a_bad_interval_and_logs_it_once(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    tid = rig.add()
    rig.service.targets.update(tid, interval_min=0)
    rig.clock.advance(DAY)
    with caplog.at_level("WARNING"):
        rig.service.tick()
        rig.service.tick()
    assert rig.service.queue.running_for(tid) is None
    assert len([r for r in caplog.records if "interval" in r.getMessage()]) == 1


def test_remove_target_drops_the_target_its_queued_job_and_its_state(rig: Rig) -> None:
    tid, other = rig.add("a"), rig.add("b")
    rig.clock.advance(DAY)
    rig.service.tick()
    pid = rig.service.queue.running_for(tid)
    assert pid is not None
    assert rig.service.remove_target(tid) is True
    assert rig.service.targets.get(tid) is None
    assert rig.service.queue.running_for(tid) is None
    assert rig.tracker.forgotten == [tid]
    assert tid not in rig.service._last_started
    assert rig.service.queue.running_for(other) is not None
    assert rig.service.remove_target(tid) is False
