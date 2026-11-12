"""Review fixes I8, I9, M17 and M20."""

import time
from typing import Any

import pytest
from conftest import HostEnv
from pydantic import BaseModel
from sample_plugins.good import GoodPlugin, GoodSettings
from sample_plugins.slow_setup import SlowSetupPlugin
from sqlalchemy import text

from netview.application.plugins.context import PluginIdentity
from netview.domain.events import DomainEvent, EventKind
from netview.infrastructure.db.engine import plugin_data_file
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
)


def test_update_settings_replaces_the_live_context_settings(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    gid = env.id(GoodPlugin)
    plugin: Any = host.plugin(gid)
    assert plugin.ctx.settings.level == 1

    host.update_settings(gid, {"level": 9})

    assert plugin.ctx.settings.level == 9


class _Two(BaseModel):
    a: int = 1
    b: int = 2


def test_patch_merges_over_current_settings(env: HostEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GoodPlugin, "settings_model", _Two)
    host = env.host([GoodPlugin], {GoodPlugin.manifest.guid: {"a": 5, "b": 6}})
    host.load_all()

    info = host.update_settings(env.id(GoodPlugin), {"a": 7})

    assert info.settings == {"a": 7, "b": 6}
    again = env.host([GoodPlugin])
    again.load_all()
    assert again.get(env.id(GoodPlugin)).settings == {"a": 7, "b": 6}
    assert GoodPlugin.settings_model is _Two and GoodSettings is not _Two


def test_hanging_setup_marks_the_plugin_failed(env: HostEnv) -> None:
    host = env.host([SlowSetupPlugin], setup_timeout_s=0.2)
    started = time.monotonic()
    host.load_all()
    assert time.monotonic() - started < 2
    info = host.get(env.id(SlowSetupPlugin))
    assert info.state == "failed"
    assert info.error is not None
    assert "setup timed out after 0.2 s" in info.error


def _context(env: HostEnv, bus: InMemoryEventBus, *, storage: bool = False) -> DefaultPluginContext:
    data_file = plugin_data_file(env.data_dir, GoodPlugin.manifest.guid) if storage else None
    return DefaultPluginContext(
        PluginIdentity(GoodPlugin.manifest.guid, 1, "Good", data_file),
        None,
        data_file,
        FakeClock(),
        FakeNetworkTools(),
        FakeVendors(),
        InMemoryMetrics(),
        None,  # type: ignore[arg-type]
        bus,
        FakeServiceProbes(),
        FakeSystemInfo(),
        FakeSnmpClient([]),
    )


def test_slow_plugin_handler_does_not_delay_publish(env: HostEnv) -> None:
    bus = InMemoryEventBus()
    ctx = _context(env, bus)
    seen: list[str] = []
    ctx.subscribe(lambda e: time.sleep(5))
    bus.subscribe(lambda e: seen.append(e.text))  # a core subscriber stays synchronous

    started = time.monotonic()
    bus.publish(DomainEvent(EventKind.NEW, "a", 1))
    bus.publish(DomainEvent(EventKind.NEW, "b", 2))
    assert time.monotonic() - started < 0.1
    assert seen == ["a", "b"]
    ctx.close()


def test_plugin_handlers_run_in_order(env: HostEnv) -> None:
    bus = InMemoryEventBus()
    ctx = _context(env, bus)
    got: list[str] = []
    ctx.subscribe(lambda e: got.append(e.text))
    for i in range(5):
        bus.publish(DomainEvent(EventKind.NEW, str(i), i))
    deadline = time.monotonic() + 2
    while len(got) < 5 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert got == ["0", "1", "2", "3", "4"]
    ctx.close()


def test_plugin_handler_exception_does_not_kill_the_worker(env: HostEnv) -> None:
    bus = InMemoryEventBus()
    ctx = _context(env, bus)
    got: list[str] = []

    def handler(e: DomainEvent) -> None:
        if e.text == "bad":
            raise RuntimeError("boom")
        got.append(e.text)

    ctx.subscribe(handler)
    bus.publish(DomainEvent(EventKind.NEW, "bad", 1))
    bus.publish(DomainEvent(EventKind.NEW, "ok", 2))
    deadline = time.monotonic() + 2
    while not got and time.monotonic() < deadline:
        time.sleep(0.01)
    assert got == ["ok"]
    ctx.close()


def test_plugin_writes_its_own_file_and_core_is_untouched(env: HostEnv) -> None:
    env.host([GoodPlugin]).load_all()
    ctx = _context(env, InMemoryEventBus(), storage=True)

    with ctx.unit_of_work() as uow:
        uow.session.execute(text("INSERT INTO items (id) VALUES (1)"))
        uow.commit()
    with ctx.unit_of_work() as uow:
        assert uow.session.execute(text("SELECT id FROM items")).scalars().all() == [1]
        with pytest.raises(Exception, match="no such table"):  # the core tables live in another file
            uow.session.execute(text("SELECT * FROM nicknames"))
    ctx.close()

    with env.uow() as core:
        core.session.execute(text("INSERT INTO nicknames (key, value) VALUES ('k', 'v')"))
        core.commit()


def test_unit_of_work_without_storage_raises(env: HostEnv) -> None:
    ctx = _context(env, InMemoryEventBus())
    with pytest.raises(RuntimeError, match="this plugin declares no storage"):
        ctx.unit_of_work()
    ctx.close()


def test_subscribe_after_close_registers_nothing(env: HostEnv) -> None:
    bus = InMemoryEventBus()
    ctx = _context(env, bus)
    ctx.close()
    got: list[str] = []

    unsubscribe = ctx.subscribe(lambda e: got.append(e.text))
    bus.publish(DomainEvent(EventKind.NEW, "late", 1))
    time.sleep(0.1)

    assert got == []
    unsubscribe()  # a no-op, must not raise
