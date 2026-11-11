from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core, upgrade_plugin
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.plugins.builtin.gsm7248.analysis import Attachment
from netview.plugins.builtin.gsm7248.model import (
    Health,
    PortCounters,
    PortRates,
    Snapshot,
)
from netview.plugins.builtin.gsm7248.storage import SwitchStore, storage_spec
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

BUCKET = 300_000


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(eng)
    upgrade_plugin(eng, "gsm7248", storage_spec().versions_dir)
    return eng


@pytest.fixture
def ctx(engine: Engine) -> DefaultPluginContext:
    c = DefaultPluginContext(
        "gsm7248",
        None,
        engine,
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
    yield c  # type: ignore[misc]
    c.close()


@pytest.fixture
def store(ctx: DefaultPluginContext) -> SwitchStore:
    return SwitchStore(ctx.unit_of_work, "gsm7248")


def _rate(if_index: int, t_ms: int, bps: float = 1000.0, util: float | None = 1.0) -> PortRates:
    return PortRates(if_index, t_ms, bps, bps * 2, 1.0, 2.0, 3.0, 4.0, util)


def _counters(if_index: int, t_ms: int, octets: int = 10) -> PortCounters:
    return PortCounters(if_index, t_ms, True, octets, octets * 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def _att(mac: str, if_index: int, vlan: int = 1) -> Attachment:
    return Attachment(mac, if_index, f"0/{if_index}", vlan, False, None)


def test_migration_creates_prefixed_tables(engine: Engine) -> None:
    names = set(sa.inspect(engine).get_table_names())
    assert {"gsm7248_port_samples", "gsm7248_mac_locations", "gsm7248_snapshots"} <= names
    assert "alembic_version_gsm7248" in names
    assert {t for t in storage_spec().metadata.tables} == {
        "gsm7248_port_samples",
        "gsm7248_mac_locations",
        "gsm7248_snapshots",
    }
    idx = {i["name"] for i in sa.inspect(engine).get_indexes("gsm7248_mac_locations")}
    assert idx


def test_snapshot_round_trip(store: SwitchStore) -> None:
    assert store.load_snapshot() is None
    snap = Snapshot(
        t_ms=1_700_000_000_000,
        groups=frozenset({"status"}),
        info=None,
        health=Health(1.0, 2, 3),
        inventory=None,
        ports=(),
        macs=(),
        vlans=(),
        pvids=((1, 10),),
        stp=(),
        lags=(),
    )
    store.save_snapshot(snap)
    assert store.load_snapshot() == snap
    newer = replace(snap, t_ms=snap.t_ms + 1)
    store.save_snapshot(newer)
    loaded = store.load_snapshot()
    assert loaded is not None and loaded.t_ms == newer.t_ms


def test_samples_query_range(store: SwitchStore) -> None:
    for i in range(5):
        t = 1_000 + i * 15_000
        store.add_samples([_rate(1, t, bps=i), _rate(2, t)], {1: _counters(1, t, i), 2: _counters(2, t)})
    got = store.samples(1, 16_000, 46_000, "raw")
    assert [r.t_ms for r in got] == [16_000, 31_000, 46_000]
    assert [r.in_bps for r in got] == [1.0, 2.0, 3.0]
    assert got[0].util_percent == 1.0
    assert store.samples(1, 0, 10**9, "5m") == []


def test_rollup_averages_and_prunes(store: SwitchStore, engine: Engine) -> None:
    base = 10 * BUCKET
    for i in range(20):  # every 30 s over 10 minutes
        t = base + i * 30_000
        store.add_samples([_rate(1, t, bps=float(i))], {1: _counters(1, t, i)})
    now = base + 3 * BUCKET
    deleted = store.rollup_and_prune(now, raw_keep_ms=BUCKET * 100, rollup_keep_ms=BUCKET * 100)
    assert deleted == 0
    rolled = store.samples(1, 0, 10**12, "5m")
    assert [r.t_ms for r in rolled] == [base, base + BUCKET]
    assert rolled[0].in_bps == pytest.approx(sum(range(10)) / 10)
    assert rolled[1].in_bps == pytest.approx(sum(range(10, 20)) / 10)
    assert rolled[0].out_bps == pytest.approx(2 * sum(range(10)) / 10)
    # idempotent
    assert store.rollup_and_prune(now, BUCKET * 100, BUCKET * 100) == 0
    assert store.samples(1, 0, 10**12, "5m") == rolled
    assert len(store.samples(1, 0, 10**12, "raw")) == 20
    # prune raw rows older than retention: the first bucket's 10 rows go, the second's stay
    deleted = store.rollup_and_prune(now, raw_keep_ms=now - (base + BUCKET), rollup_keep_ms=BUCKET * 100)
    assert deleted == 10
    assert len(store.samples(1, 0, 10**12, "raw")) == 10
    assert store.samples(1, 0, 10**12, "5m") == rolled  # pruning raw must not change rollups
    assert store.rollup_and_prune(now, now - (base + BUCKET), BUCKET * 100) == 0
    # old rollups are pruned
    deleted = store.rollup_and_prune(now, raw_keep_ms=BUCKET * 100, rollup_keep_ms=now - (base + BUCKET))
    assert deleted == 1
    assert [r.t_ms for r in store.samples(1, 0, 10**12, "5m")] == [base + BUCKET]


def test_rollup_skips_incomplete_bucket(store: SwitchStore) -> None:
    base = 10 * BUCKET
    store.add_samples([_rate(1, base + 1000)], {1: _counters(1, base + 1000)})
    store.rollup_and_prune(base + BUCKET - 1, BUCKET * 100, BUCKET * 100)
    assert store.samples(1, 0, 10**12, "5m") == []


def test_touch_macs_updates_last_seen(store: SwitchStore) -> None:
    assert store.seen_macs() == frozenset()
    store.touch_macs([_att("aa:aa:aa:aa:aa:01", 5), _att("aa:aa:aa:aa:aa:02", 6)], 1000)
    store.touch_macs([_att("aa:aa:aa:aa:aa:01", 5)], 5000)
    assert store.seen_macs() == frozenset({"aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:02"})
    row = next(r for r in store.mac_history(mac="aa:aa:aa:aa:aa:01"))
    assert (row["first_ms"], row["last_ms"]) == (1000, 5000)
    assert row["if_index"] == 5 and row["vlan"] == 1


def test_mac_history_by_port(store: SwitchStore) -> None:
    store.touch_macs([_att("aa:aa:aa:aa:aa:01", 5), _att("aa:aa:aa:aa:aa:02", 6)], 1000)
    store.touch_macs([_att("aa:aa:aa:aa:aa:01", 7)], 2000)  # moved
    by_port = store.mac_history(if_index=5)
    assert [r["mac"] for r in by_port] == ["aa:aa:aa:aa:aa:01"]
    by_mac = store.mac_history(mac="aa:aa:aa:aa:aa:01")
    assert [r["if_index"] for r in by_mac] == [7, 5]  # newest first
    assert len(store.mac_history()) == 3
    assert len(store.mac_history(limit=2)) == 2
    assert set(by_mac[0]) == {"mac", "vlan", "if_index", "first_ms", "last_ms"}


def test_cannot_write_core_tables(ctx: DefaultPluginContext) -> None:
    with ctx.unit_of_work() as uow, pytest.raises(sa.exc.DatabaseError):
        uow.session.execute(
            sa.text(
                "INSERT INTO devices (key, ip, first_seen_ms, last_seen_ms, status) "
                "VALUES ('k', '10.0.0.1', 1, 1, 'up')"
            ),
        )
