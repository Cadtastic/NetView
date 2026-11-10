from collections.abc import Iterator
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netview.infrastructure.settings import AppSettings
from netview.plugins.builtin.lan_discovery.plugin import LanDiscoveryPlugin
from netview.plugins.builtin.lan_discovery.settings import LanDiscoverySettings
from netview.sdk import Capability, PingResult, PluginManifest
from netview.sdk.testing.contract import _FakeContext, check_plugin
from netview.sdk.testing.fakes import FakeNetworkTools

SUBNET = IPv4Network("192.168.1.0/29")


def make_plugin(net: FakeNetworkTools) -> LanDiscoveryPlugin:
    plugin = LanDiscoveryPlugin()
    plugin.settings = LanDiscoverySettings()
    ctx = _FakeContext("lan_discovery", plugin.settings)
    ctx.net = net
    plugin.setup(ctx)  # type: ignore[arg-type]
    return plugin


def discover(plugin: LanDiscoveryPlugin) -> list[Any]:
    provider: Any = plugin.providers()[Capability.DISCOVERY]
    return list(provider.discover(SUBNET))


def test_contract() -> None:
    check_plugin(LanDiscoveryPlugin)


def test_manifest() -> None:
    m: PluginManifest = LanDiscoveryPlugin.manifest
    assert m.id == "lan_discovery"
    assert m.sdk_version == ">=1.0,<2"


def test_settings_bounds() -> None:
    with pytest.raises(ValueError):
        LanDiscoverySettings(ping_timeout_ms=50)
    with pytest.raises(ValueError):
        LanDiscoverySettings(workers=257)


def test_discover_yields_replies_and_arp_only() -> None:
    net = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(1.5, 64)},
        arp={"192.168.1.74": "aa:bb:cc:dd:ee:74"},
    )
    sightings = discover(make_plugin(net))
    by_ip = {s.ip: s for s in sightings}
    assert set(by_ip) == {"192.168.1.1", "192.168.1.74"}
    assert by_ip["192.168.1.1"].rtt_ms == 1.5
    assert by_ip["192.168.1.74"].rtt_ms is None
    assert by_ip["192.168.1.74"].mac == "aa:bb:cc:dd:ee:74"
    assert by_ip["192.168.1.74"].seen_ms == 1_800_000_000_000


def test_discover_with_no_network() -> None:
    assert discover(make_plugin(FakeNetworkTools(fail=True))) == []


def test_summary_route() -> None:
    net = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(1.5, 64), "192.168.1.2": PingResult(2.0, 64)},
        arp={"192.168.1.74": "aa:bb:cc:dd:ee:74", "192.168.1.1": "aa:bb:cc:dd:ee:01"},
    )
    plugin = make_plugin(net)
    app = FastAPI()
    app.include_router(plugin.router())
    client = TestClient(app)

    assert client.get("/summary").json() == {
        "hosts": 0,
        "replied": 0,
        "arp_only": 0,
        "duration_ms": 0,
        "last_ms": None,
    }
    discover(plugin)
    body = client.get("/summary").json()
    assert body["hosts"] == 6  # a /29 has six usable hosts
    assert body["replied"] == 2
    assert body["arp_only"] == 1  # .74 is in the ARP table but did not reply
    assert body["last_ms"] == 1_800_000_000_000
    assert body["duration_ms"] >= 0


@pytest.fixture
def e2e_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    fake = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(1.0, 64), "192.168.1.20": PingResult(3.0, 128)},
        arp={"192.168.1.1": "aa:bb:cc:00:00:01", "192.168.1.20": "aa:bb:cc:00:00:20"},
    )
    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: fake)
    from netview.bootstrap import create_application

    app = create_application(AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24"))
    with TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"}) as client:
        yield client


def test_end_to_end_scan(e2e_client: TestClient) -> None:
    assert e2e_client.post("/api/v1/scan").status_code == 200
    devices = e2e_client.get("/api/v1/devices").json()
    ips = {d["ip"] for d in (devices if isinstance(devices, list) else devices["devices"])}
    assert {"192.168.1.1", "192.168.1.20"} <= ips
    assert e2e_client.get("/api/v1/plugins/lan_discovery/summary").json()["replied"] == 2
