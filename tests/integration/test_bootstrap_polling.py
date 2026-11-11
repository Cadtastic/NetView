"""The bootstrap poller and the startup hostname claim."""

import sys
from pathlib import Path

import pytest

import netview.bootstrap
from netview.application.capabilities import Capability
from netview.bootstrap import build_container
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
        "discover_plugin_classes",
        lambda extra_dirs=(): [DiscoveredPlugin("test:poller", PollerPlugin, None)],
    )
    container = build_container(AppSettings(data_dir=tmp_path, fast_interval_s=7.0))
    container.host.start_jobs()

    jobs = {(j.owner, j.name) for j in container.scheduler.status()}
    assert ("poller", "poll.health") in jobs
    assert ("poller", "own") in jobs
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
