"""Review fixes I8, I9, M17 and M20."""

import time
from typing import Any

import pytest
from conftest import HostEnv
from pydantic import BaseModel
from sample_plugins.good import GoodPlugin, GoodSettings
from sample_plugins.slow_setup import SlowSetupPlugin
from sqlalchemy import text

from netview.domain.events import DomainEvent, EventKind
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
)


def test_update_settings_replaces_the_live_context_settings(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    plugin: Any = host.plugin("good")
    assert plugin.ctx.settings.level == 1

    host.update_settings("good", {"level": 9})

    assert plugin.ctx.settings.level == 9


class _Two(BaseModel):
    a: int = 1
    b: int = 2


def test_patch_merges_over_current_settings(env: HostEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GoodPlugin, "settings_model", _Two)
    host = env.host([GoodPlugin], {"good": {"a": 5, "b": 6}})
    host.load_all()

    info = host.update_settings("good", {"a": 7})

    assert info.settings == {"a": 7, "b": 6}
    again = env.host([GoodPlugin])
    again.load_all()
    assert again.get("good").settings == {"a": 7, "b": 6}
    assert GoodPlugin.settings_model is _Two and GoodSettings is not _Two


def test_hanging_setup_marks_the_plugin_failed(env: HostEnv) -> None:
    host = env.host([SlowSetupPlugin], setup_timeout_s=0.2)
    started = time.monotonic()
    host.load_all()
    assert time.monotonic() - started < 2
    info = host.get("slow_setup")
    assert info.state == "failed"
    assert info.error is not None
    assert "setup timed out after 0.2 s" in info.error


def _context(env: HostEnv, plugin_id: str, bus: InMemoryEventBus) -> DefaultPluginContext:
    return DefaultPluginContext(
        plugin_id,
        None,
        env.engine,
        FakeClock(),
        FakeNetworkTools(),
        FakeVendors(),
        InMemoryMetrics(),
        None,  # type: ignore[arg-type]
        bus,
        FakeServiceProbes(),
        FakeSystemInfo(),
    )


def test_slow_plugin_handler_does_not_delay_publish(env: HostEnv) -> None:
    bus = InMemoryEventBus()
    ctx = _context(env, "good", bus)
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
    ctx = _context(env, "good", bus)
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
    ctx = _context(env, "good", bus)
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


def test_plugin_write_fence(env: HostEnv) -> None:
    env.host([GoodPlugin]).load_all()
    ctx = _context(env, "good", InMemoryEventBus())

    with ctx.unit_of_work() as uow:
        uow.session.execute(text("INSERT INTO good_items (id) VALUES (1)"))
        uow.commit()

    for sql in (
        "INSERT INTO nicknames (key, value) VALUES ('k', 'v')",
        "UPDATE nicknames SET value = 'x'",
        "DELETE FROM nicknames",
    ):
        with ctx.unit_of_work() as uow, pytest.raises(Exception, match="not authorized"):
            uow.session.execute(text(sql))

    with ctx.unit_of_work() as uow:  # reads of core tables are still allowed
        uow.session.execute(text("SELECT * FROM nicknames")).all()
    ctx.close()

    # the core connections are unaffected
    with env.uow() as core:
        core.session.execute(text("INSERT INTO nicknames (key, value) VALUES ('k', 'v')"))
        core.commit()


def test_plugin_ddl_fence(env: HostEnv) -> None:
    env.host([GoodPlugin]).load_all()
    ctx = _context(env, "good", InMemoryEventBus())

    for sql in (
        "DROP TABLE nicknames",
        "CREATE TABLE other_x (id INTEGER)",
        "ALTER TABLE nicknames ADD COLUMN extra TEXT",
        "CREATE INDEX ix_nick_value ON nicknames (value)",
        "CREATE TRIGGER good_t AFTER INSERT ON nicknames BEGIN DELETE FROM nicknames; END",
        "CREATE TEMP TRIGGER good_tt AFTER INSERT ON nicknames BEGIN DELETE FROM nicknames; END",
        "CREATE VIEW other_v AS SELECT * FROM nicknames",
        "CREATE TEMP VIEW other_tv AS SELECT * FROM nicknames",
        "CREATE TEMP TABLE other_tmp (id INTEGER)",
    ):
        with ctx.unit_of_work() as uow, pytest.raises(Exception, match="not authorized"):
            uow.session.execute(text(sql))

    with ctx.unit_of_work() as uow:  # the plugin's own namespace is open
        uow.session.execute(text("CREATE TABLE good_x (id INTEGER)"))
        uow.session.execute(text("CREATE INDEX ix_good_x_id ON good_x (id)"))
        uow.session.execute(text("ALTER TABLE good_x ADD COLUMN extra TEXT"))
        uow.session.execute(text("DROP INDEX ix_good_x_id"))
        uow.session.execute(text("CREATE VIEW good_v AS SELECT id FROM good_x"))
        uow.session.execute(text("CREATE TRIGGER good_x_t AFTER INSERT ON good_x BEGIN SELECT 1; END"))
        uow.session.execute(text("DROP TRIGGER good_x_t"))
        uow.session.execute(text("DROP VIEW good_v"))
        uow.session.execute(text("DROP TABLE good_x"))
        uow.commit()

    with ctx.unit_of_work() as uow:  # a fenced attempt left the core table alone
        uow.session.execute(text("SELECT * FROM nicknames")).all()
    ctx.close()


def test_subscribe_after_close_registers_nothing(env: HostEnv) -> None:
    bus = InMemoryEventBus()
    ctx = _context(env, "good", bus)
    ctx.close()
    got: list[str] = []

    unsubscribe = ctx.subscribe(lambda e: got.append(e.text))
    bus.publish(DomainEvent(EventKind.NEW, "late", 1))
    time.sleep(0.1)

    assert got == []
    unsubscribe()  # a no-op, must not raise
