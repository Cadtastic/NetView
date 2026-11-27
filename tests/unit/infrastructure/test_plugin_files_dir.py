"""The per-plugin files folder: beside the plugin's database, created on first access."""

from pathlib import Path

import pytest

from netview.application.plugins.context import PluginIdentity
from netview.infrastructure.db.engine import plugin_data_file, plugin_files_dir
from netview.infrastructure.plugins.context import DefaultPluginContext
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

GUID = "c66a564b-0254-44cf-bb74-1c7f6ebae6be"


def test_files_dir_is_beside_the_db_and_created_lazily(tmp_path: Path) -> None:
    files = plugin_files_dir(tmp_path, GUID)
    assert files == tmp_path / "plugin-data" / GUID
    assert files.parent == plugin_data_file(tmp_path, GUID).parent
    ctx = DefaultPluginContext(
        PluginIdentity(GUID, 1, "Demo", None, files),
        None,
        None,
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
    assert not files.exists()
    assert ctx.files_dir == files
    assert files.is_dir()


def test_fake_context_gives_a_real_folder() -> None:
    ctx = FakePluginContext(None, snmp=None, core=FakeCore())
    assert ctx.files_dir.is_dir()
    assert ctx.files_dir == ctx.files_dir


def test_fake_context_uses_the_given_folder(tmp_path: Path) -> None:
    target = tmp_path / "f"
    ctx = FakePluginContext(None, snmp=None, core=FakeCore(), files_dir=target)
    assert ctx.files_dir == target
    assert target.is_dir()


def test_files_dir_after_close_raises_and_creates_nothing(tmp_path: Path) -> None:
    files = plugin_files_dir(tmp_path, GUID)
    ctx = DefaultPluginContext(
        PluginIdentity(GUID, 1, "Demo", None, files),
        None,
        None,
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
    ctx.close()
    with pytest.raises(RuntimeError, match="stopped"):
        _ = ctx.files_dir
    assert not files.exists()
