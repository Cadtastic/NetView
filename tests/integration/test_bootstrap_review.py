"""Review fix C1 end to end: network changes, no network, and import claim handling (M16)."""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

import netview.bootstrap
from netview.bootstrap import build_container
from netview.domain.device import Device, DeviceStatus
from netview.domain.errors import NoNetworkError, ScanInProgressError
from netview.domain.naming import NameClaim
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.infrastructure.settings import AppSettings
from netview.sdk import PingResult
from netview.sdk.testing.fakes import FakeNetworkTools


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeNetworkTools) -> None:
    monkeypatch.setattr(netview.bootstrap, "SystemNetworkTools", lambda: fake)


def _settings(tmp_path: Path, **extra: Any) -> AppSettings:
    return AppSettings(data_dir=tmp_path, **extra)


def test_loopback_address_never_fills_the_repository(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeNetworkTools(
        replies={f"127.0.0.{i}": PingResult(0.1, 128) for i in range(1, 255)}, local="127.0.0.1"
    )
    _patch(monkeypatch, fake)
    container = build_container(_settings(tmp_path))
    with pytest.raises(NoNetworkError):
        container.services.run_scan()
    assert container.services.state().devices == []
    container.engine.dispose()


def test_subnet_and_host_ip_follow_the_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeNetworkTools(local="192.168.1.95")
    _patch(monkeypatch, fake)
    clock = {"now": 1000.0}
    monkeypatch.setattr(netview.bootstrap.time, "monotonic", lambda: clock["now"])
    container = build_container(_settings(tmp_path))
    assert container.services.state().host.ip == "192.168.1.95"
    assert container.services.state().host.subnet == "192.168.1.0/24"

    fake.local = "10.0.0.5"
    fake.replies = {"10.0.0.7": PingResult(2.0, 64)}
    clock["now"] += 31  # the 30 s host cache has expired
    state = container.services.state()
    assert state.host.ip == "10.0.0.5" and state.host.subnet == "10.0.0.0/24"
    container.services.run_scan()
    assert "10.0.0.7" in {d.ip for d in container.services.state().devices}
    container.engine.dispose()


def test_configured_subnet_is_not_rederived(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeNetworkTools(local="192.168.1.95", replies={"10.1.2.7": PingResult(2.0, 64)})
    _patch(monkeypatch, fake)
    container = build_container(_settings(tmp_path, subnet="10.1.2.0/25"))
    fake.local = "172.16.0.9"
    container.services.run_scan()
    assert [d.ip for d in container.services.state().devices if d.ip == "10.1.2.7"] == ["10.1.2.7"]
    container.engine.dispose()


def test_startup_clears_the_new_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeNetworkTools()
    _patch(monkeypatch, fake)
    container = build_container(_settings(tmp_path))

    sessions = sessionmaker(container.engine)
    with SqlUnitOfWork(sessions) as uow:
        uow.devices.add(Device("ip:10.0.0.9", "10.0.0.9", None, "", 1, 2, DeviceStatus.ONLINE, is_new=True))
        uow.commit()
    container.engine.dispose()
    again = build_container(_settings(tmp_path))
    assert not any(d.is_new for d in again.services.state().devices)
    again.engine.dispose()


def test_import_skips_name_claim_when_same_source_claim_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:

    _patch(monkeypatch, FakeNetworkTools())
    container = build_container(_settings(tmp_path))
    store = tmp_path / "lan_store.json"
    mac = "aa:bb:cc:00:00:01"
    store.write_text(
        json.dumps(
            {
                "schema": "ketiv.network-tools/lan-store@1",
                "known": {mac: {"ip": "192.168.1.5", "mac": mac, "name": "old-name", "name_source": "DNS"}},
            }
        ),
        encoding="utf-8",
    )
    container.importer.run(store)  # first import creates the claim

    sessions = sessionmaker(container.engine)
    with SqlUnitOfWork(sessions) as uow:  # a live probe refreshes the claim
        uow.identity.upsert_claim(NameClaim(mac, "fresh-name", "DNS", 2, 99999))
        uow.commit()
    container.importer.run(store)
    with SqlUnitOfWork(sessions) as uow:
        claims = uow.identity.claims(mac)
        assert [(c.name, c.checked_ms) for c in claims] == [("fresh-name", 99999)]
    container.engine.dispose()


def test_scheduled_scan_logs_no_network_once_and_skips_busy_silently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:

    _patch(monkeypatch, FakeNetworkTools())
    container = build_container(_settings(tmp_path))
    job = netview.bootstrap._scan_job(container)
    mode: list[Exception | None] = [NoNetworkError()]

    def fake_scan() -> None:
        if mode[0] is not None:
            raise mode[0]

    container.services.run_scan = fake_scan  # type: ignore[assignment]
    with caplog.at_level("INFO"):
        job()
        job()
        assert len([r for r in caplog.records if "no network" in r.getMessage()]) == 1
        mode[0] = ScanInProgressError()
        caplog.clear()
        job()
        assert caplog.records == []
        mode[0] = None
        job()
        mode[0] = NoNetworkError()
        job()  # a new state change logs again
        assert len([r for r in caplog.records if "no network" in r.getMessage()]) == 1
    container.engine.dispose()
