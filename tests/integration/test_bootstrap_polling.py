"""The bootstrap poller and the startup hostname claim."""

import sys
from pathlib import Path

import pytest

import netview.bootstrap
from netview.application.capabilities import Capability
from netview.bootstrap import build_container
from netview.domain.watch import WatchProbe, WatchState
from netview.infrastructure.clock import SystemClock
from netview.infrastructure.plugins.discovery import DiscoveredPlugin
from netview.infrastructure.settings import AppSettings
from netview.sdk.testing.fakes import FakeNetworkTools

sys.path.insert(0, str(Path(__file__).parent / "plugins"))
from sample_plugins.pollers import PollerPlugin


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        netview.bootstrap, "SystemNetworkTools", lambda: FakeNetworkTools(gateway=None, fail=True)
    )


def test_the_poller_schedules_poll_health_at_the_fast_interval(
    offline: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        netview.bootstrap,
        "find_entry_points",
        lambda group="netview.plugins": [DiscoveredPlugin("test:poller", PollerPlugin, None)],
    )
    container = build_container(AppSettings(data_dir=tmp_path, fast_interval_s=7.0))
    container.host.start_jobs()

    jobs = {(j.owner, j.name) for j in container.scheduler.status()}
    pid = str(container.host.list()[0].source_id)
    assert (pid, "poll.health") in jobs
    assert (pid, "own") in jobs
    container.host.shutdown()
    container.engine.dispose()


def test_the_poller_ignores_capabilities_the_core_does_not_poll(offline: None, tmp_path: Path) -> None:
    container = build_container(AppSettings(data_dir=tmp_path))
    poller = container.host._poller
    assert poller is not None
    for capability in (Capability.DISCOVERY, Capability.INSPECTION, Capability.LOCAL_HOST):
        assert poller("x", capability, object()) is None
    health = poller("x", Capability.HEALTH, object())
    identity = poller("x", Capability.IDENTITY, object())
    traffic = poller("x", Capability.TRAFFIC, object())
    assert health is not None
    assert (health.name, health.interval_s, health.timeout_s) == ("poll.health", 5.0, 30)
    assert identity is not None
    assert (identity.name, identity.interval_s, identity.timeout_s, identity.initial_delay_s) == (
        "poll.identity",
        60.0,
        120,
        10,
    )
    assert traffic is not None
    assert (traffic.name, traffic.interval_s, traffic.timeout_s) == ("poll.traffic", 5.0, 15)
    container.engine.dispose()


def test_startup_claims_this_devices_hostname(offline: None, tmp_path: Path) -> None:
    container = build_container(AppSettings(data_dir=tmp_path))
    with container.services.state._uow() as uow:  # type: ignore[attr-defined]
        [claim] = uow.identity.claims("self")
        assert uow.events.recent(10) == []  # not news: no event
    assert (claim.name, claim.source, claim.rank) == ("test-host", "hostname", 9)
    container.engine.dispose()


def test_removing_and_re_adding_a_watch_through_the_services_starts_it_over(
    offline: None, tmp_path: Path
) -> None:
    container = build_container(AppSettings(data_dir=tmp_path))
    poller = container.host._poller
    assert poller is not None
    ip = "192.0.2.77"
    clock = SystemClock()

    class Provider:
        def __init__(self) -> None:
            self.checked_ms = clock.now_ms()

        def probe(self, targets: object) -> list[WatchProbe]:
            return [WatchProbe(ip, self.checked_ms, True, None, None, 1.0, {})]

    provider = Provider()
    spec = poller("x", Capability.HEALTH, provider)
    assert spec is not None

    def state() -> object:
        return next(w.state for w in container.services.state().watch_status if w.ip == ip)

    container.services.add_watch(ip)
    provider.checked_ms = clock.now_ms() + 1_000
    spec.run()
    assert state() is WatchState.UP
    stale_ms = provider.checked_ms  # a probe that was in flight while the watch was replaced
    container.services.remove_watch(ip)
    container.services.add_watch(ip)
    assert state() is WatchState.PENDING  # the old result went with the old watch
    provider.checked_ms = stale_ms - 5_000
    spec.run()
    assert state() is WatchState.PENDING
    provider.checked_ms = clock.now_ms() + 1_000
    spec.run()
    assert state() is WatchState.UP
    container.engine.dispose()
