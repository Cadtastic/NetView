from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from netview_local_plugins.gs105e.model import PortCounters, PortRates, PortStatus, Snapshot
from netview_local_plugins.gs105e.storage import SwitchStore, storage_spec

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

GUID = "c66a564b-0254-44cf-bb74-1c7f6ebae6be"
BUCKET = 300_000
GRACE = 120_000


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    path = plugin_data_file(tmp_path, GUID)
    eng = make_plugin_engine(path)
    upgrade_plugin(eng, storage_spec().versions_dir)
    eng.dispose()
    return path


@pytest.fixture
def ctx(data_file: Path) -> Iterator[DefaultPluginContext]:
    c = DefaultPluginContext(
        PluginIdentity(GUID, 1, "GS105E", data_file),
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
    yield c
    c.close()


@pytest.fixture
def store(ctx: DefaultPluginContext) -> SwitchStore:
    return SwitchStore(ctx.unit_of_work, "gs105e")


def _rate(port: int, t_ms: int, bps: float = 1000.0, crc: int | None = 1) -> PortRates:
    return PortRates(port, t_ms, bps, bps * 2, crc, 1.5)  # type: ignore[arg-type]


def _counters(port: int, t_ms: int, n: int = 10) -> PortCounters:
    return PortCounters(port, t_ms, n, n * 2, n * 3)


def test_migration_creates_unprefixed_tables(data_file: Path) -> None:
    eng = make_plugin_engine(data_file)
    names = set(sa.inspect(eng).get_table_names())
    eng.dispose()
    assert {"port_samples", "snapshots", "alembic_version"} <= names
    assert set(storage_spec().metadata.tables) == {"port_samples", "snapshots"}


def test_samples_come_back_in_time_order(store: SwitchStore) -> None:
    for i in (3, 1, 0, 4, 2):
        t = 1_000 + i * 15_000
        store.add_samples([_rate(1, t, bps=i), _rate(2, t)], {1: _counters(1, t, i), 2: _counters(2, t)})
    got = store.samples(1, 16_000, 46_000, "raw")
    assert [r.t_ms for r in got] == [16_000, 31_000, 46_000]
    assert [r.in_bps for r in got] == [1.0, 2.0, 3.0]
    assert got[0].util_percent == 1.5
    assert store.samples(1, 0, 10**9, "5m") == []


def test_rollup_writes_5m_rows_and_sums_crc(store: SwitchStore) -> None:
    base = 10 * BUCKET
    for i in range(20):
        t = base + i * 30_000
        store.add_samples([_rate(1, t, bps=float(i), crc=1)], {1: _counters(1, t, i)})
    now = base + 3 * BUCKET + GRACE
    assert store.rollup_and_prune(now, BUCKET * 100, BUCKET * 100) == 0
    rolled = store.samples(1, 0, 10**12, "5m")
    assert [r.t_ms for r in rolled] == [base, base + BUCKET]
    assert rolled[0].in_bps == pytest.approx(sum(range(10)) / 10)
    assert rolled[1].in_bps == pytest.approx(sum(range(10, 20)) / 10)
    assert [r.crc_delta for r in rolled] == [10, 10]


def test_second_rollup_writes_nothing_new(store: SwitchStore) -> None:
    base = 10 * BUCKET
    for i in range(10):
        t = base + i * 30_000
        store.add_samples([_rate(1, t)], {1: _counters(1, t)})
    now = base + 2 * BUCKET + GRACE
    store.rollup_and_prune(now, BUCKET * 100, BUCKET * 100)
    first = store.samples(1, 0, 10**12, "5m")
    assert len(first) == 1
    assert store.rollup_and_prune(now, BUCKET * 100, BUCKET * 100) == 0
    assert store.samples(1, 0, 10**12, "5m") == first


def test_incomplete_bucket_is_not_rolled_up(store: SwitchStore) -> None:
    base = 10 * BUCKET
    store.add_samples([_rate(1, base + 1000)], {1: _counters(1, base + 1000)})
    store.rollup_and_prune(base + BUCKET - 1, BUCKET * 100, BUCKET * 100)
    assert store.samples(1, 0, 10**12, "5m") == []


def test_late_written_sample_is_in_the_rollup(store: SwitchStore) -> None:
    base = 10 * BUCKET
    boundary = base + BUCKET
    store.add_samples([_rate(1, base + 1000, bps=0.0)], {1: _counters(1, base + 1000)})
    store.rollup_and_prune(boundary + 1, BUCKET * 100, BUCKET * 100)
    assert store.samples(1, 0, 10**12, "5m") == []
    # stamped before the boundary, written after it
    store.add_samples([_rate(1, boundary - 1, bps=10.0)], {1: _counters(1, boundary - 1)})
    store.rollup_and_prune(boundary + GRACE, BUCKET * 100, BUCKET * 100)
    rolled = store.samples(1, 0, 10**12, "5m")
    assert [r.t_ms for r in rolled] == [base]
    assert rolled[0].in_bps == pytest.approx(5.0)


def test_prune_deletes_old_raw_rows_and_counts_them(store: SwitchStore) -> None:
    base = 10 * BUCKET
    for i in range(20):
        t = base + i * 30_000
        store.add_samples([_rate(1, t)], {1: _counters(1, t)})
    now = base + 3 * BUCKET + GRACE
    assert store.rollup_and_prune(now, now - (base + BUCKET), BUCKET * 100) == 10
    assert len(store.samples(1, 0, 10**12, "raw")) == 10
    assert len(store.samples(1, 0, 10**12, "5m")) == 2
    assert store.rollup_and_prune(now, now - (base + BUCKET), BUCKET * 100) == 0
    assert store.rollup_and_prune(now, BUCKET * 100, now - (base + BUCKET)) == 1


def test_snapshot_round_trip(store: SwitchStore) -> None:
    assert store.load_snapshot() is None
    snap = Snapshot(
        t_ms=1_700_000_000_000,
        groups=frozenset({"status"}),
        info=None,
        ports=(PortStatus(1, "uplink", True, "Auto", 1000, True, 9216),),
        vlans=None,
        qos=None,
        igmp=None,
        mirror=None,
        management=None,
    )
    store.save_snapshot(snap)
    assert store.load_snapshot() == snap
    newer = replace(snap, t_ms=snap.t_ms + 1)
    store.save_snapshot(newer)
    loaded = store.load_snapshot()
    assert loaded is not None and loaded.t_ms == newer.t_ms


def test_cannot_write_core_tables(ctx: DefaultPluginContext) -> None:
    with ctx.unit_of_work() as uow, pytest.raises(sa.exc.DatabaseError):
        uow.session.execute(
            sa.text(
                "INSERT INTO devices (key, ip, first_seen_ms, last_seen_ms, status) "
                "VALUES ('k', '10.0.0.1', 1, 1, 'up')"
            ),
        )
