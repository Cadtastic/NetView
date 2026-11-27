from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from netview_local_plugins.geotrace.model import Hop, Target, Trace
from netview_local_plugins.geotrace.storage import TargetStore, TraceStore, storage_spec

from netview.application.plugins.context import PluginIdentity
from netview.infrastructure.db.engine import make_plugin_engine, plugin_data_file
from netview.infrastructure.db.migrate import upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
    RecordingEventBus,
)

DAY = 86_400_000


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[TargetStore, TraceStore]]:
    guid = "f64f43b1-9ff2-47b9-badf-390b2fef25db"
    data_file = plugin_data_file(tmp_path, guid)
    engine = make_plugin_engine(data_file)
    upgrade_plugin(engine, storage_spec().versions_dir)
    engine.dispose()
    ctx = DefaultPluginContext(
        PluginIdentity(guid, 1, "GeoTrace", data_file),
        None,
        data_file,
        FakeClock(),
        FakeNetworkTools(),
        FakeVendors(),
        InMemoryMetrics(),
        None,  # type: ignore[arg-type]
        RecordingEventBus(),
        FakeServiceProbes(),
        FakeSystemInfo(),
        FakeSnmpClient([]),
    )
    yield TargetStore(ctx.unit_of_work), TraceStore(ctx.unit_of_work)
    ctx.close()


def _hops() -> tuple[Hop, ...]:
    return (
        Hop(1, "192.168.1.1", (0.4, 0.5, 0.6), "", "", "", None, None, None, "", "home", True),
        Hop(2, None, (None, None, None), "", "", "", None, None, None, "", "none", True),
        Hop(
            3, "8.8.8.8", (12.5, None, 13.0), "Mountain View", "CA", "US", 37.4, -122.1, 15169,
            "Google", "located", True,
        ),
    )  # fmt: skip


def _trace(target_id: int | None, started_ms: int, **kw: object) -> Trace:
    base: dict[str, object] = {
        "id": 0, "target_id": target_id, "trigger": "scheduled", "mode": "trace", "status": "done",
        "error": None, "started_ms": started_ms, "finished_ms": started_ms + 900, "resolved_ip": "8.8.8.8",
        "family": "ipv4", "reached": True, "hop_count": 3, "rtt_ms": 13.0, "loss_pct": 0.0,
        "jitter_ms": 0.5, "ping_min_ms": 12.0, "ping_max_ms": 14.0, "signature": '[[15169, "Mountain View"]]',
        "hops": _hops(),
    }  # fmt: skip
    base.update(kw)
    return Trace(**base)  # type: ignore[arg-type]


def _target(targets: TargetStore, name: str = "dns") -> Target:
    return targets.add(name, "8.8.8.8", "ipv4", 15, True, 1000)


def test_target_add_get_update_list_count(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, _ = stores
    t = _target(targets)
    assert t == Target(t.id, "dns", "8.8.8.8", "ipv4", 15, True, 1000, 1000)
    assert targets.get(t.id) == t
    assert targets.get(999) is None
    updated = targets.update(t.id, name="google", enabled=False, interval_min=60, updated_ms=2000)
    assert updated == replace(t, name="google", enabled=False, interval_min=60, updated_ms=2000)
    assert targets.update(999, name="x") is None
    _target(targets, "other")
    assert [x.name for x in targets.list()] == ["google", "other"]
    assert targets.count() == 2


def test_trace_round_trip_with_silent_hop(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t = _target(targets)
    tid = traces.save(_trace(t.id, 5000))
    got = traces.get(tid)
    assert got == _trace(t.id, 5000, id=tid)
    assert got is not None
    assert got.hops[1].ip is None
    assert got.hops[1].rtts_ms == (None, None, None)
    assert got.hops[2].rtts_ms == (12.5, None, 13.0)
    assert traces.get(tid + 100) is None


def test_latest_is_newest_first_and_filters_status(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t = _target(targets)
    for ms in (1000, 3000, 2000):
        traces.save(_trace(t.id, ms))
    traces.save(_trace(t.id, 4000, status="failed", error="boom", hops=()))
    assert [x.started_ms for x in traces.latest(t.id, n=2)] == [3000, 2000]
    assert [x.started_ms for x in traces.latest(t.id)] == [3000]
    assert [x.started_ms for x in traces.latest(t.id, status="failed")] == [4000]
    assert [x.started_ms for x in traces.latest(t.id, n=3, status=None)] == [4000, 3000, 2000]
    assert traces.latest(t.id)[0].hops != ()


def test_delete_target_cascades(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t, other = _target(targets), _target(targets, "b")
    tid = traces.save(_trace(t.id, 1000))
    oid = traces.save(_trace(other.id, 1000))
    assert targets.delete(t.id) is True
    assert targets.delete(t.id) is False
    assert traces.get(tid) is None
    kept = traces.get(oid)
    assert kept is not None and len(kept.hops) == 3


def test_deleted_ids_are_never_reused(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    first = _target(targets)
    first_trace = traces.save(_trace(first.id, 1000))
    assert targets.delete(first.id) is True
    second = _target(targets, "b")
    assert second.id > first.id
    assert traces.save(_trace(second.id, 2000)) > first_trace


def test_newest_is_the_highest_id(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t = _target(targets)
    traces.save(_trace(t.id, 9000))
    later = traces.save(_trace(t.id, 1000))
    newest = traces.newest()
    assert newest is not None and newest.id == later


def test_delete_older_respects_two_cutoffs(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t = _target(targets)
    old_t = traces.save(_trace(t.id, 100))
    mid_t = traces.save(_trace(t.id, 600))  # between the cutoffs: must survive the one-off cutoff
    new_t = traces.save(_trace(t.id, 900))
    old_once = traces.save(_trace(None, 800, trigger="once"))
    new_once = traces.save(_trace(None, 950, trigger="once"))
    assert traces.delete_older(500, 900) == 2
    assert traces.get(old_t) is None
    assert traces.get(old_once) is None
    assert traces.get(mid_t) is not None
    assert traces.get(new_t) is not None
    assert traces.get(new_once) is not None


def test_page_pages_with_before_ms_and_has_no_hops(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t = _target(targets)
    for ms in (1000, 2000, 3000, 4000, 5000):
        traces.save(_trace(t.id, ms))
    first = traces.page(t.id, None, 2)
    assert [x.started_ms for x in first] == [5000, 4000]
    assert all(x.hops == () for x in first)
    second = traces.page(t.id, first[-1].started_ms, 2)
    assert [x.started_ms for x in second] == [3000, 2000]
    assert [x.started_ms for x in traces.page(t.id, 2000, 10)] == [1000]


def test_between_is_inclusive_oldest_first_without_hops(stores: tuple[TargetStore, TraceStore]) -> None:
    targets, traces = stores
    t = _target(targets)
    for ms in (1000, 2000, 3000):
        traces.save(_trace(t.id, ms))
    got = traces.between(t.id, 1000, 2000)
    assert [x.started_ms for x in got] == [1000, 2000]
    assert all(x.hops == () for x in got)
