from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from netview_local_plugins.roku.model import SavedTv
from netview_local_plugins.roku.storage import TvStore, storage_spec

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


@pytest.fixture
def store(tmp_path: Path) -> Iterator[TvStore]:
    guid = "241d4d28-4a70-406c-833c-a7b4d5b389a9"
    data_file = plugin_data_file(tmp_path, guid)
    engine = make_plugin_engine(data_file)
    upgrade_plugin(engine, storage_spec().versions_dir)
    engine.dispose()
    ctx = DefaultPluginContext(
        PluginIdentity(guid, 1, "Roku", data_file),
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
