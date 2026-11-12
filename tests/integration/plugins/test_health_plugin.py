from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import netview.bootstrap
from netview.bootstrap import build_container
from netview.infrastructure.settings import AppSettings
from netview.plugins.builtin.health.plugin import HealthPlugin
from netview.plugins.builtin.health.settings import HealthSettings
from netview.presentation.api.app import create_app
from netview.sdk import (
    Capability,
    HealthTargets,
    LatencySample,
    PingResult,
    PluginManifest,
    TcpResult,
    Watch,
    WatchProbe,
)
from netview.sdk.testing.auth import admin_cookies
from netview.sdk.testing.contract import _FakeContext, check_plugin
from netview.sdk.testing.fakes import FakeNetworkTools

SUBNET = IPv4Network("192.168.1.0/24")
NOW = 1_800_000_000_000


class RecordingNetwork(FakeNetworkTools):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.arp_reads = 0
        self.tcp: dict[tuple[str, int], str] = {}

    def arp_table(self) -> dict[str, str]:
        self.arp_reads += 1
        return super().arp_table()

    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult:
        return TcpResult(self.tcp.get((ip, port), "filtered"), None)  # type: ignore[arg-type]


def make_plugin(net: FakeNetworkTools, settings: HealthSettings | None = None) -> HealthPlugin:
    plugin = HealthPlugin()
    plugin.settings = settings or HealthSettings()
    ctx = _FakeContext("health", plugin.settings)
    ctx.net = net
    plugin.setup(ctx)  # type: ignore[arg-type]
    return plugin


def probe(plugin: HealthPlugin, targets: HealthTargets) -> list[Any]:
    provider: Any = plugin.providers()[Capability.HEALTH]
    return list(provider.probe(targets))


def targets(
    gateway: str | None = "192.168.1.1",
    devices: tuple[tuple[str, str], ...] = (),
    watches: tuple[Watch, ...] = (),
) -> HealthTargets:
    return HealthTargets(gateway, SUBNET, devices, watches)


def samples(items: list[Any]) -> dict[str, float | None]:
    return {i.series: i.rtt_ms for i in items if isinstance(i, LatencySample)}


def test_contract() -> None:
    check_plugin(HealthPlugin)


def test_manifest() -> None:
    m: PluginManifest = HealthPlugin.manifest
    assert (m.id, m.name, m.version) == ("health", "Health", "0.1.0")
    assert m.sdk_version == ">=1.1,<2"
    assert m.capabilities == {Capability.HEALTH, Capability.API, Capability.WEB_UI}
    assert {p.value for p in m.permissions} == {"devices:read", "network:probe", "api", "ui"}


def test_settings_defaults_and_limits() -> None:
    s = HealthSettings()
    assert (s.internet_target, s.dns_servers) == ("1.1.1.1", [])
    assert (s.ping_timeout_ms, s.internet_timeout_ms) == (1000, 1500)
    assert (s.port_timeout_s, s.max_devices) == (1.5, 64)
    assert s.dns_names[0] == "www.google.com"
    for bad in (
        {"internet_target": "not an ip"},
        {"dns_servers": ["1.1.1.1", "8.8.8.8", "9.9.9.9"]},
        {"dns_servers": ["dns.example"]},
        {"ping_timeout_ms": 50},
        {"internet_timeout_ms": 5001},
        {"port_timeout_s": 0.1},
        {"port_timeout_s": 11},
        {"max_devices": 65},
        {"max_devices": -1},
    ):
        with pytest.raises(ValueError):
            HealthSettings(**bad)
    assert HealthSettings(max_devices=0).max_devices == 0


def test_probe_returns_latency_dns_and_device_samples_with_one_time() -> None:
    net = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(2.0, 64), "192.168.1.20": PingResult(4.0, 64)},
        dns={"192.168.1.1": 15.0},
    )
    result = probe(
        make_plugin(net),
        targets(devices=(("aa:01", "192.168.1.20"), ("aa:02", "192.168.1.21"))),
    )
    assert samples(result) == {
        "health.gateway": 2.0,
        "health.internet": None,
        "health.dns.192.168.1.1": 15.0,
        "health.dns.1.1.1.1": None,
        "health.device.aa:01": 4.0,
        "health.device.aa:02": None,
    }
    assert {s.t_ms for s in result if isinstance(s, LatencySample)} == {NOW}


def test_the_internet_target_and_configured_dns_servers_are_used() -> None:
    net = FakeNetworkTools(replies={"9.9.9.9": PingResult(12.0, 60)}, dns={"8.8.8.8": 20.0, "8.8.4.4": 25.0})
    settings = HealthSettings(internet_target="9.9.9.9", dns_servers=["8.8.8.8", "8.8.4.4"])
    got = samples(probe(make_plugin(net, settings), targets()))
    assert got["health.internet"] == 12.0
    assert got["health.dns.8.8.8.8"] == 20.0
    assert got["health.dns.8.8.4.4"] == 25.0
    assert "health.dns.1.1.1.1" not in got


def test_no_gateway_still_writes_a_null_gateway_sample_and_never_raises() -> None:
    """Review focus 4."""
    net = FakeNetworkTools(gateway=None, dns={"1.1.1.1": 9.0})
    result = probe(make_plugin(net), targets(gateway=None))
    got = samples(result)
    assert got["health.gateway"] is None
    assert got["health.dns.1.1.1.1"] == 9.0
    assert [k for k in got if k.startswith("health.dns.")] == ["health.dns.1.1.1.1"]


def test_a_gateway_that_is_the_internet_target_is_not_listed_twice_in_dns() -> None:
    got = samples(probe(make_plugin(FakeNetworkTools(gateway="1.1.1.1")), targets(gateway="1.1.1.1")))
    assert [k for k in got if k.startswith("health.dns.")] == ["health.dns.1.1.1.1"]


def test_a_probe_that_raises_gives_none_and_probe_does_not_raise() -> None:
    class Broken(FakeNetworkTools):
        def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
            raise OSError("no route")

        def dns_query(self, server: str, name: str, timeout_s: float = 2.0) -> float | None:
            raise OSError("no route")

        def arp_table(self) -> dict[str, str]:
            raise OSError("no arp")

    result = probe(
        make_plugin(Broken()),
        targets(devices=(("aa:01", "192.168.1.20"),), watches=(Watch("192.168.1.30"),)),
    )
    got = samples(result)
    assert got["health.gateway"] is None
    assert got["health.device.aa:01"] is None
    assert got["health.dns.192.168.1.1"] is None
    [watch] = [r for r in result if isinstance(r, WatchProbe)]
    assert watch.rtt_ms is None and watch.mac is None


def test_max_devices_limits_the_device_pings() -> None:
    devices = tuple((f"aa:0{i}", f"192.168.1.{20 + i}") for i in range(3))
    result = probe(make_plugin(FakeNetworkTools(), HealthSettings(max_devices=1)), targets(devices=devices))
    assert [k for k in samples(result) if k.startswith("health.device.")] == ["health.device.aa:00"]


def test_a_watch_on_the_subnet_pings_probes_ports_and_reads_arp() -> None:
    net = RecordingNetwork(
        replies={"192.168.1.30": PingResult(3.0, 64)}, arp={"192.168.1.30": "aa:bb:cc:00:00:30"}
    )
    net.tcp[("192.168.1.30", 22)] = "open"
    net.tcp[("192.168.1.30", 80)] = "closed"
    [watch] = [
        r
        for r in probe(make_plugin(net), targets(watches=(Watch("192.168.1.30", (22, 80)),)))
        if isinstance(r, WatchProbe)
    ]
    assert watch == WatchProbe(
        "192.168.1.30", NOW, True, True, "aa:bb:cc:00:00:30", 3.0, {22: "open", 80: "closed"}
    )
    assert net.arp_reads == 1


def test_a_watch_outside_the_subnet_has_no_l2_and_the_arp_table_is_not_read() -> None:
    """Review focus 4."""
    net = RecordingNetwork(replies={"10.9.9.9": PingResult(30.0, 60)})
    [watch] = [
        r for r in probe(make_plugin(net), targets(watches=(Watch("10.9.9.9"),))) if isinstance(r, WatchProbe)
    ]
    assert (watch.on_subnet, watch.l2, watch.mac, watch.rtt_ms) == (False, None, None, 30.0)
    assert net.arp_reads == 0


def test_a_watch_with_no_reply_reads_no_reply_not_a_crash() -> None:
    net = RecordingNetwork()
    result = probe(make_plugin(net), targets(watches=(Watch("10.9.9.9", (443,)),)))
    [watch] = [r for r in result if isinstance(r, WatchProbe)]
    assert (watch.rtt_ms, watch.ports) == (None, {443: "filtered"})


def test_summary_route_uses_current_settings_and_the_gateway() -> None:
    plugin = HealthPlugin()
    plugin.settings = HealthSettings()
    ctx = _FakeContext("health", plugin.settings)
    ctx.core.host.return_value.gateway = "192.168.1.1"
    plugin.setup(ctx)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(plugin.router())
    client = TestClient(app)
    assert client.get("/summary").json() == {
        "gateway": "192.168.1.1",
        "internet": "1.1.1.1",
        "dns": ["192.168.1.1", "1.1.1.1"],
    }
    plugin.on_settings_changed(HealthSettings(internet_target="9.9.9.9", dns_servers=["8.8.8.8"]))
    assert client.get("/summary").json() == {
        "gateway": "192.168.1.1",
        "internet": "9.9.9.9",
        "dns": ["8.8.8.8"],
    }
    ctx.core.host.return_value.gateway = None
    plugin.on_settings_changed(HealthSettings())
    assert client.get("/summary").json()["gateway"] is None
    assert client.get("/summary").json()["dns"] == ["1.1.1.1"]


def test_end_to_end_one_poll_health_run_fills_the_gateway_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(2.5, 64)},
        gateway="192.168.1.1",
        local="192.168.1.95",
        dns={"192.168.1.1": 11.0},
    )
    monkeypatch.setattr(netview.bootstrap, "SystemNetworkTools", lambda: fake)
    container = build_container(AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24"))
    try:
        [(owner, provider)] = container.registry.providers(Capability.HEALTH)
        assert owner == "health"
        poller = container.host._poller
        assert poller is not None
        spec = poller(owner, Capability.HEALTH, provider)
        assert spec is not None and spec.name == "poll.health"
        spec.run()

        app = create_app(
            container.services,
            container.host.routers(),
            container.host.ui_contributions(),
            {"localhost"},
        )
        client = TestClient(
            app,
            base_url="http://localhost",
            headers={"X-Netview": "1"},
            cookies=admin_cookies(app.state.services),
        )
        series = client.get("/api/v1/metrics").json()["series"]
        assert series["health.gateway"][0][1] == 2.5
        assert series["health.internet"][0][1] is None
        assert series["health.dns.192.168.1.1"][0][1] == 11.0
        assert client.get("/api/v1/plugins/health/summary").json()["dns"] == ["192.168.1.1", "1.1.1.1"]
    finally:
        container.host.shutdown()
        container.engine.dispose()
