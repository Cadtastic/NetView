from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from netview_local_plugins.roku.model import SavedTv
from netview_local_plugins.roku.storage import TvStore, storage_spec

from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core, upgrade_plugin
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


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TvStore]:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    upgrade_plugin(engine, "roku", storage_spec().versions_dir)
    ctx = DefaultPluginContext(
        "roku",
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
    yield TvStore(ctx.unit_of_work)
    ctx.close()


def _tv(id: str, ip: str, **kw: object) -> SavedTv:
    base: dict[str, object] = {
        "id": id, "serial": f"S{id}", "ip": ip, "name": f"TV {id}", "label": "", "model": "M",
        "location": "http://x", "tv": True, "found_by": "ssdp", "first_seen": "t0", "last_seen": "t1",
    }  # fmt: skip
    base.update(kw)
    return SavedTv(**base)


def test_replace_then_load_keeps_order_and_fields(store: TvStore) -> None:
    tvs = [
        _tv("z", "192.168.1.62", label="Den", tv=False),
        _tv("a", "192.168.1.60"),
        _tv("m", "192.168.1.61"),
    ]
    store.replace(tvs)
    assert store.load() == tvs


def test_replace_removes_rows_not_in_the_new_list(store: TvStore) -> None:
    store.replace([_tv("a", "192.168.1.60"), _tv("b", "192.168.1.61")])
    store.replace([_tv("b", "192.168.1.61", label="Kept")])
    assert store.load() == [_tv("b", "192.168.1.61", label="Kept")]
    store.replace([])
    assert store.load() == []
