import time
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
from netview.sdk.testing.addresses import api_base
from netview.sdk.testing.auth import admin_cookies
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
    assert m.display_name == "LAN discovery"
    assert m.sdk_version == ">=2.0,<3"


def test_settings_bounds() -> None:
    with pytest.raises(ValueError):
        LanDiscoverySettings(ping_timeout_ms=50)
    with pytest.raises(ValueError):
        LanDiscoverySettings(workers=257)


def test_discover_yields_replies_and_arp_only() -> None:
    net = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(1.5, 64)},
        arp={"192.168.1.4": "aa:bb:cc:dd:ee:04", "172.21.0.5": "aa:bb:cc:dd:ee:55"},
    )
    sightings = discover(make_plugin(net))
    by_ip = {s.ip: s for s in sightings}
    assert set(by_ip) == {"192.168.1.1", "192.168.1.4"}  # 172.21.0.5 is outside the subnet
    assert by_ip["192.168.1.1"].rtt_ms == 1.5
    assert by_ip["192.168.1.4"].rtt_ms is None
    assert by_ip["192.168.1.4"].mac == "aa:bb:cc:dd:ee:04"
    assert by_ip["192.168.1.4"].seen_ms == 1_800_000_000_000


def test_discover_with_no_network() -> None:
    assert discover(make_plugin(FakeNetworkTools(fail=True))) == []


def test_summary_route() -> None:
    net = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(1.5, 64), "192.168.1.2": PingResult(2.0, 64)},
        arp={
            "192.168.1.4": "aa:bb:cc:dd:ee:04",
            "192.168.1.1": "aa:bb:cc:dd:ee:01",
            "172.21.0.5": "aa:bb:cc:dd:ee:55",
        },
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
    assert body["arp_only"] == 1  # .4 is in the ARP table but did not reply; 172.21.0.5 is outside the subnet
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
    with TestClient(
        app,
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies=admin_cookies(app.state.services),
    ) as client:
        yield client


def test_end_to_end_scan(e2e_client: TestClient) -> None:
    # the scheduler's own first sweep may be running at startup; scans run one at a time (409)
    for _ in range(100):
        status = e2e_client.post("/api/v1/scan").status_code
        if status != 409:
            break
        time.sleep(0.05)
    assert status == 200
    devices = e2e_client.get("/api/v1/devices").json()
    ips = {d["ip"] for d in (devices if isinstance(devices, list) else devices["devices"])}
    assert {"192.168.1.1", "192.168.1.20"} <= ips
    assert (
        e2e_client.get(
            f"{api_base(e2e_client.app.state.services, LanDiscoveryPlugin.manifest.guid)}/summary"
        ).json()["replied"]
        == 2
    )


def test_every_discover_call_updates_the_summary() -> None:
    """The scheduled core scan calls the same provider, so /summary must follow each discover()."""
    net = FakeNetworkTools(replies={"192.168.1.1": PingResult(1.5, 64)})
    plugin = make_plugin(net)
    assert plugin.summary()["last_ms"] is None
    discover(plugin)
    first = plugin.summary()
    assert first["last_ms"] is not None
    assert first["replied"] == 1
    assert first["hosts"] == 6
    net.replies["192.168.1.2"] = PingResult(2.0, 64)
    discover(plugin)
    assert plugin.summary()["replied"] == 2
