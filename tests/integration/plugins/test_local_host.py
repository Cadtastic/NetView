from ipaddress import IPv4Network
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import netview.bootstrap
from netview.bootstrap import build_container
from netview.infrastructure.settings import AppSettings
from netview.plugins.builtin.local_host.connections import COMMON_PORTS, summarize
from netview.plugins.builtin.local_host.plugin import LocalHostPlugin
from netview.plugins.builtin.local_host.settings import LocalHostSettings
from netview.presentation.api.app import create_app
from netview.sdk import Capability, JobSpec, PluginManifest, TcpSocket, Watch, WifiInfo
from netview.sdk.testing.contract import _FakeContext, check_plugin
from netview.sdk.testing.fakes import FakeClock, FakeSystemInfo

SUBNET = IPv4Network("192.168.1.0/24")
SELF_IP = "192.168.1.95"


def make_plugin(
    system: FakeSystemInfo | None = None, settings: LocalHostSettings | None = None
) -> tuple[LocalHostPlugin, _FakeContext]:
    plugin = LocalHostPlugin()
    plugin.settings = settings or LocalHostSettings()
    ctx = _FakeContext("local_host", plugin.settings)
    if system is not None:
        ctx.system = system
    ctx.core.host.return_value.subnet = "192.168.1.0/24"
    ctx.core.device_by_ip.return_value = None
    ctx.core.watches.return_value = []
    plugin.setup(ctx)  # type: ignore[arg-type]
    return plugin, ctx


def advance(ctx: _FakeContext, ms: int) -> None:
    clock = ctx.clock
    assert isinstance(clock, FakeClock)
    clock.advance(ms)


def job(plugin: LocalHostPlugin, name: str) -> JobSpec:
    [spec] = [j for j in plugin.jobs() if j.name == name]
    return spec


def sock(
    remote: str, port: int, state: str = "ESTABLISHED", process: str = "chrome", local_port: int = 50000
) -> TcpSocket:
    return TcpSocket(SELF_IP, local_port, remote, port, state, process)


def test_contract() -> None:
    check_plugin(LocalHostPlugin)


def test_manifest() -> None:
    m: PluginManifest = LocalHostPlugin.manifest
    assert (m.id, m.name, m.version) == ("local_host", "This device", "0.1.0")
    assert m.description == "This device's throughput, Wi-Fi link and TCP connections"
    assert m.sdk_version == ">=1.1,<2"
    assert m.capabilities == {Capability.LOCAL_HOST, Capability.API, Capability.WEB_UI, Capability.JOBS}
    assert {p.value for p in m.permissions} == {"devices:read", "api", "ui"}


def test_settings_defaults_and_limits() -> None:
    s = LocalHostSettings()
    assert (s.throughput_interval_s, s.connections_interval_s) == (5.0, 10.0)
    for bad in (
        {"throughput_interval_s": 0.5},
        {"throughput_interval_s": 61},
        {"connections_interval_s": 4},
        {"connections_interval_s": 121},
    ):
        with pytest.raises(ValueError):
            LocalHostSettings(**bad)


def test_jobs_use_the_configured_intervals() -> None:
    plugin, _ = make_plugin(settings=LocalHostSettings(throughput_interval_s=2, connections_interval_s=30))
    assert {j.name: j.interval_s for j in plugin.jobs()} == {"throughput": 2, "snapshot": 30}


def test_throughput_is_bits_per_second_and_a_counter_reset_gives_none_then_recovers() -> None:
    """Review focus 2."""
    system = FakeSystemInfo(interface_bytes=[(1000, 500), (6000, 1500), (10, 10), (110, 60)])
    plugin, ctx = make_plugin(system)
    run = job(plugin, "throughput").run
    run()
    advance(ctx, 5000)
    run()
    advance(ctx, 5000)
    run()  # the counters went backwards
    advance(ctx, 5000)
    run()  # the next sample recovers
    down = [v for _, v in ctx.metrics.series("local.down_bps")]
    up = [v for _, v in ctx.metrics.series("local.up_bps")]
    assert down == [None, 8000.0, None, 160.0]
    assert up == [None, 1600.0, None, 80.0]


def test_throughput_with_unreadable_counters_appends_none_and_keeps_the_last_reading() -> None:
    system = FakeSystemInfo(interface_bytes=[(0, 0), None, (1250, 625)])
    plugin, ctx = make_plugin(system)
    run = job(plugin, "throughput").run
    for _ in range(3):
        run()
        advance(ctx, 5000)
    assert [v for _, v in ctx.metrics.series("local.down_bps")] == [None, None, 1000.0]


def test_no_time_between_readings_gives_none() -> None:
    plugin, ctx = make_plugin(FakeSystemInfo(interface_bytes=[(0, 0), (1000, 1000)]))
    run = job(plugin, "throughput").run
    run()
    run()  # the clock did not move
    assert [v for _, v in ctx.metrics.series("local.up_bps")] == [None, None]


def test_summarize_groups_sorts_and_skips() -> None:
    sockets = [
        sock("142.250.1.1", 443, local_port=50001),
        sock("142.250.1.1", 443, local_port=50002),
        sock("192.168.1.128", 443, "SYN_SENT", "msedge", 50003),
        sock("127.0.0.1", 8000, process="python"),
        sock("0.0.0.0", 0, "TIME_WAIT"),
        TcpSocket("0.0.0.0", 8080, "0.0.0.0", 0, "LISTENING", "node"),
        TcpSocket("0.0.0.0", 22, "0.0.0.0", 0, "LISTEN", "sshd"),
        sock("192.168.1.10", 445, process="System"),
        sock("100.64.1.2", 22, process="ssh"),
    ]
    names = {"192.168.1.128": "R720 iDRAC"}
    got = summarize(sockets, SUBNET, lambda ip: names.get(ip, ""))
    assert got["total"] == len(sockets)
    assert got["states"] == {"ESTABLISHED": 5, "SYN_SENT": 1, "TIME_WAIT": 1, "LISTENING": 1, "LISTEN": 1}
    assert got["remotes"][0] == {
        "process": "chrome",
        "remote": "142.250.1.1",
        "port": 443,
        "service": "HTTPS",
        "count": 2,
        "scope": "internet",
        "name": "",
    }
    assert {(r["remote"], r["scope"]) for r in got["remotes"]} == {
        ("142.250.1.1", "internet"),
        ("192.168.1.10", "lan"),
        ("100.64.1.2", "private"),
    }
    assert got["trying"] == [
        {
            "process": "msedge",
            "remote": "192.168.1.128",
            "port": 443,
            "service": "HTTPS",
            "count": 1,
            "scope": "lan",
            "name": "R720 iDRAC",
        }
    ]
    assert got["listening"] == [
        {"port": 22, "addr": "0.0.0.0", "process": "sshd"},
        {"port": 8080, "addr": "0.0.0.0", "process": "node"},
    ]
    assert got["unique_remotes"] == 3
    assert got["lan_conns"] == 1


def test_summarize_limits_the_lists_to_60_40_and_20() -> None:
    sockets = [TcpSocket("0.0.0.0", p, "0.0.0.0", 0, "LISTENING", "svc") for p in range(1, 100)]
    sockets += [sock(f"8.8.{i // 250}.{i % 250 + 1}", 443) for i in range(100)]
    sockets += [sock(f"9.9.{i // 250}.{i % 250 + 1}", 443, "SYN_SENT") for i in range(50)]
    got = summarize(sockets, SUBNET, lambda ip: "")
    assert (len(got["listening"]), len(got["remotes"]), len(got["trying"])) == (60, 40, 20)
    assert got["unique_remotes"] == 100  # counted before the limit, as LM does


def test_summarize_service_names_unusual_addresses_and_empty_input() -> None:
    got = summarize([sock("203.0.113.5", 9100, process=""), sock("not-an-ip", 1)], SUBNET, lambda ip: "")
    by_remote = {r["remote"]: r for r in got["remotes"]}
    assert by_remote["203.0.113.5"]["service"] == "Printer"
    assert by_remote["203.0.113.5"]["process"] == ""
    assert by_remote["not-an-ip"]["scope"] == "other"
    assert dict(COMMON_PORTS)[8060] == "Roku"
    assert summarize([], SUBNET, lambda ip: "") == {
        "total": 0,
        "states": {},
        "listening": [],
        "remotes": [],
        "trying": [],
        "unique_remotes": 0,
        "lan_conns": 0,
    }


def test_snapshot_provider_returns_wifi_and_connections() -> None:
    wifi = WifiInfo(ssid="Home", band="5 GHz", channel="36", signal_pct=82, rx_rate_mbps=866.0)
    system = FakeSystemInfo(
        wifi=wifi, sockets=[sock("142.250.1.1", 443), sock("192.168.1.128", 443, "SYN_SENT")]
    )
    plugin, ctx = make_plugin(system)
    ctx.core.watches.return_value = [Watch("192.168.1.128", (443,), "iDRAC")]
    provider: Any = plugin.providers()[Capability.LOCAL_HOST]
    snap = provider.snapshot()
    assert snap["t_ms"] == ctx.clock.now_ms()
    assert snap["interval_s"] == 10.0  # the card says how often it refreshes
    assert snap["wifi"]["ssid"] == "Home" and snap["wifi"]["signal_pct"] == 82
    assert snap["connections"]["total"] == 2
    assert snap["connections"]["trying"][0]["name"] == "iDRAC"


def test_name_for_prefers_the_device_name_then_the_watch_label() -> None:
    plugin, ctx = make_plugin(FakeSystemInfo(sockets=[sock("192.168.1.20", 80), sock("192.168.1.30", 80)]))
    ctx.core.device_by_ip.side_effect = lambda ip: (
        SimpleNamespace(display_name="Roku TV") if ip == "192.168.1.20" else None
    )
    ctx.core.watches.return_value = [Watch("192.168.1.30", (), "Printer")]
    provider: Any = plugin.providers()[Capability.LOCAL_HOST]
    rows = {r["remote"]: r["name"] for r in provider.snapshot()["connections"]["remotes"]}
    assert rows == {"192.168.1.20": "Roku TV", "192.168.1.30": "Printer"}


def test_a_device_with_no_name_falls_through_to_the_watch_label() -> None:
    plugin, ctx = make_plugin(FakeSystemInfo(sockets=[sock("192.168.1.30", 80)]))
    ctx.core.device_by_ip.side_effect = lambda ip: SimpleNamespace(display_name="")
    ctx.core.watches.return_value = [Watch("192.168.1.30", (), "Printer")]
    [row] = plugin.snapshot()["connections"]["remotes"]
    assert row["name"] == "Printer"


def test_no_wifi_gives_none_and_failing_readers_do_not_raise() -> None:
    class Broken(FakeSystemInfo):
        def tcp_sockets(self) -> list[TcpSocket]:
            raise OSError("netstat missing")

        def wifi(self) -> WifiInfo | None:
            raise OSError("netsh missing")

        def interface_bytes(self) -> tuple[int, int] | None:
            raise OSError("no counters")

    plugin, ctx = make_plugin(Broken())
    job(plugin, "snapshot").run()
    job(plugin, "throughput").run()
    snap = plugin.snapshot()
    assert snap["wifi"] is None
    assert snap["connections"]["total"] == 0
    assert [v for _, v in ctx.metrics.series("local.down_bps")] == [None]


def test_snapshot_is_cached_until_the_job_refreshes_it() -> None:
    plugin, ctx = make_plugin(FakeSystemInfo(sockets=[sock("142.250.1.1", 443)]))
    first = plugin.snapshot()
    advance(ctx, 10_000)
    assert plugin.snapshot() == first
    job(plugin, "snapshot").run()
    assert plugin.snapshot()["t_ms"] == first["t_ms"] + 10_000


def test_the_snapshot_route_returns_the_summary() -> None:
    plugin, _ = make_plugin(FakeSystemInfo(wifi=WifiInfo(ssid="Home"), sockets=[sock("142.250.1.1", 443)]))
    app = FastAPI()
    app.include_router(plugin.router())
    body = TestClient(app).get("/snapshot").json()
    assert body["wifi"]["ssid"] == "Home"
    assert body["connections"]["remotes"][0]["remote"] == "142.250.1.1"
    assert isinstance(body["t_ms"], int)


def test_end_to_end_through_the_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    system = FakeSystemInfo(
        interface_bytes=[(0, 0), (625_000, 125_000)],
        wifi=WifiInfo(ssid="Home", signal_pct=80),
        sockets=[sock("142.250.1.1", 443, process="chrome")],
    )
    monkeypatch.setattr(netview.bootstrap, "SystemSystemInfo", lambda: system)
    container = build_container(AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24"))
    try:
        [(owner, provider)] = container.registry.providers(Capability.LOCAL_HOST)
        assert owner == "local_host"
        app = create_app(
            container.services, container.host.routers(), container.host.ui_contributions(), {"localhost"}
        )
        client = TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"})
        body = client.get("/api/v1/plugins/local_host/snapshot").json()
        assert body["wifi"]["ssid"] == "Home"
        assert body["connections"]["remotes"][0]["service"] == "HTTPS"
        assert provider.snapshot()["connections"]["total"] == 1
    finally:
        container.host.shutdown()
        container.engine.dispose()
