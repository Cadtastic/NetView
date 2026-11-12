import json
import threading
from pathlib import Path
from typing import Any

import pytest
from conftest import HostEnv
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import netview.bootstrap
from netview.application.usecases.inspection import RunInspection
from netview.infrastructure.plugins.discovery import DiscoveredPlugin
from netview.plugins.builtin.inspection.analysis import analyze_port, mdns_info, ssdp_info
from netview.plugins.builtin.inspection.plugin import InspectionPlugin
from netview.plugins.builtin.inspection.settings import InspectionSettings
from netview.presentation.cli import app as cli_app
from netview.sdk import (
    Capability,
    CertInfo,
    DeviceView,
    DnsRecord,
    Hint,
    HttpProbe,
    NameClaim,
    NetbiosInfo,
    NetbiosName,
    PingResult,
    PluginManifest,
    SsdpEntry,
    TcpResult,
    TypeClaim,
)
from netview.sdk.testing.contract import _FakeContext, check_plugin
from netview.sdk.testing.fakes import FakeClock, FakeNetworkTools, FakeServiceProbes, FakeVendors

NOW = FakeClock().now_ms()
IP = "192.0.2.10"
GRPC = b"\x00\x00\x12\x04\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x64"


def http(port: int = 80, **kw: Any) -> HttpProbe:
    fields: dict[str, Any] = {
        "scheme": "http",
        "url": f"http://{IP}{'' if port == 80 else f':{port}'}/",
        "status": 200,
        "reason": "OK",
        "server": "nginx",
        "powered_by": "",
        "location": "",
        "title": "Home",
        "generator": "",
        "auth": "",
        "realm": "",
        "tls": None,
        "cert": None,
    }
    fields.update(kw)
    return HttpProbe(**fields)


class ScanNetwork(FakeNetworkTools):
    def __init__(self, open_ports: tuple[int, ...] = (), closed: tuple[int, ...] = (), **kw: Any) -> None:
        super().__init__(**kw)
        self.open_ports = set(open_ports)
        self.closed = set(closed)
        self.timeouts: set[float] = set()
        self.probed = 0
        self._lock = threading.Lock()

    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult:
        with self._lock:
            self.timeouts.add(timeout_s)
            self.probed += 1
        if port in self.open_ports:
            return TcpResult("open", 1.0)
        return TcpResult("closed" if port in self.closed else "filtered", None)


class CountingProbes(FakeServiceProbes):
    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[str] = []
        self.tls_order: list[bool] = []

    def http_probe(self, ip: str, port: int, tls: bool, timeout_s: float = 3.0) -> HttpProbe | None:
        self.calls.append("http")
        self.tls_order.append(tls)
        return super().http_probe(ip, port, tls, timeout_s)

    def tcp_banner(self, ip: str, port: int, timeout_s: float = 2.0) -> bytes | None:
        self.calls.append("banner")
        return super().tcp_banner(ip, port, timeout_s)

    def mdns_query(self, ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]:
        self.calls.append("mdns")
        return super().mdns_query(ip, qname, qtype, timeout_s)


def device(ip: str = IP, is_self: bool = False, mac: str | None = "a8:bb:cc:00:00:01") -> DeviceView:
    return DeviceView(
        key=f"k-{ip}",
        ip=ip,
        mac=mac,
        vendor="",
        nickname=None,
        device_name="",
        name_source="",
        type="",
        hints=[],
        status="online",
        rtt_ms=None,
        ttl=None,
        first_seen_ms=0,
        last_seen_ms=0,
        is_new=False,
        is_self=is_self,
        watched=False,
        display_name="",
    )


def make_plugin(
    net: FakeNetworkTools | None = None,
    probes: FakeServiceProbes | None = None,
    known: DeviceView | None = None,
    vendors: FakeVendors | None = None,
    settings: InspectionSettings | None = None,
) -> tuple[InspectionPlugin, Any]:
    plugin = InspectionPlugin()
    plugin.settings = settings or InspectionSettings()
    ctx = _FakeContext("inspection", plugin.settings)
    ctx.net = net or ScanNetwork()
    ctx.probes = probes or FakeServiceProbes()
    ctx.vendors = vendors or FakeVendors()
    ctx.core.device_by_ip.return_value = known
    plugin.setup(ctx)  # type: ignore[arg-type]
    return plugin, ctx


def inspect(plugin: InspectionPlugin, ports: str = "top", ip: str = IP) -> dict[str, Any]:
    provider: Any = plugin.providers()[Capability.INSPECTION]
    return {s.id: s for s in provider.inspect(ip, ports)}


def ids(plugin: InspectionPlugin, ports: str, ip: str = IP) -> list[str]:
    provider: Any = plugin.providers()[Capability.INSPECTION]
    return [s.id for s in provider.inspect(ip, ports)]


# ---------------------------------------------------------------- contract


def test_contract() -> None:
    check_plugin(InspectionPlugin)


def test_manifest() -> None:
    m: PluginManifest = InspectionPlugin.manifest
    assert (m.name, m.version) == ("Inspection", "0.1.0")
    assert m.sdk_version == ">=2.0,<3"
    assert m.capabilities == {Capability.INSPECTION, Capability.API, Capability.WEB_UI}
    assert {p.value for p in m.permissions} == {
        "devices:read",
        "names:write",
        "types:write",
        "network:probe",
        "api",
        "ui",
    }


def test_settings_defaults_and_limits() -> None:
    s = InspectionSettings()
    assert (s.workers, s.port_timeout_s, s.full_scan_timeout_s, s.max_analyzed) == (256, 0.8, 0.5, 64)
    for bad in ({"workers": 15}, {"workers": 1025}, {"max_analyzed": 0}, {"max_analyzed": 257}):
        with pytest.raises(ValueError):
            InspectionSettings(**bad)


# ---------------------------------------------------------------- analysis


def test_a_server_that_sends_http2_settings_first_is_called_a_grpc_api() -> None:
    probes = FakeServiceProbes(banners={(IP, 9000): GRPC})
    info = analyze_port(probes, IP, 9000)
    assert info == {
        "port": 9000,
        "name": "HTTP-alt/gRPC",
        "banner": "HTTP/2 without TLS (server sent SETTINGS first): usually a gRPC API",
    }


def test_a_greeting_becomes_a_clean_one_line_banner() -> None:
    probes = FakeServiceProbes(banners={(IP, 22): b"SSH-2.0-OpenSSH_9.6\r\n\x00\x01"})
    assert analyze_port(probes, IP, 22)["banner"] == "SSH-2.0-OpenSSH_9.6"


def test_a_binary_greeting_with_no_text_falls_through_to_the_http_probe() -> None:
    probes = CountingProbes(banners={(IP, 80): b"\x01\x02\xff"}, http={(IP, 80): http()})
    info = analyze_port(probes, IP, 80)
    assert "banner" not in info
    assert info["http"]["title"] == "Home"


def test_an_unreachable_port_returns_only_its_name() -> None:
    assert analyze_port(FakeServiceProbes(), IP, 22) == {"port": 22, "name": "SSH"}


def test_a_silent_port_is_probed_as_http_then_tls_and_a_tls_first_port_the_other_way_round() -> None:
    plain = CountingProbes(banners={(IP, 80): b""})
    assert analyze_port(plain, IP, 80) == {"port": 80, "name": "HTTP"}
    assert plain.tls_order == [False, True]
    tls = CountingProbes(banners={(IP, 443): b""})
    analyze_port(tls, IP, 443)
    assert tls.tls_order == [True, False]


def test_a_tls_only_answer_ends_the_probing_and_the_certificate_is_kept() -> None:
    cert = CertInfo(
        "abc", "Router", "SpaceX", "SpaceX Router CA", "SpaceX", "Jan  1 2030", False, ("a.test",)
    )
    probe = http(443, scheme="https", status=None, reason="", title="", server="", tls="TLSv1.3", cert=cert)
    probes = CountingProbes(banners={(IP, 443): b""}, http={(IP, 443): probe})
    info = analyze_port(probes, IP, 443)
    assert probes.tls_order == [True]
    assert info["http"]["cert"]["issuer"] == "SpaceX Router CA"
    assert info["http"]["cert"]["san"] == ["a.test"]
    json.dumps(info)  # everything in the report must be plain JSON


def test_mdns_info_reads_the_host_the_services_and_the_useful_txt_keys() -> None:
    rev = "10.2.0.192.in-addr.arpa"
    svc = "_services._dns-sd._udp.local"
    inst = "Den TV._airplay._tcp.local"
    probes = FakeServiceProbes(
        mdns={
            (IP, rev): [DnsRecord(rev, 12, "den-tv.local")],
            (IP, svc): [DnsRecord(svc, 12, "_airplay._tcp.local"), DnsRecord("other", 12, "ignored")],
            (IP, "_airplay._tcp.local"): [
                DnsRecord("_airplay._tcp.local", 12, inst),
                DnsRecord(inst, 16, ("manufacturer=LG", "deviceid=aa:bb", "model=OLED", "pk=zz")),
            ],
        }
    )
    assert mdns_info(probes, IP) == {
        "hostname": "den-tv.local",
        "services": [
            {
                "type": "_airplay._tcp.local",
                "instances": ["Den TV"],
                "txt": {"manufacturer": "LG", "model": "OLED"},
            }
        ],
    }
    assert mdns_info(FakeServiceProbes(), IP) is None


def test_mdns_info_takes_the_host_from_an_address_record_when_there_is_no_ptr() -> None:
    svc = "_services._dns-sd._udp.local"
    probes = FakeServiceProbes(
        mdns={
            (IP, svc): [DnsRecord(svc, 12, "_hap._tcp.local")],
            (IP, "_hap._tcp.local"): [DnsRecord("bridge.local", 1, IP)],
        }
    )
    info = mdns_info(probes, IP)
    assert info is not None and info["hostname"] == "bridge.local"


def test_ssdp_info_keeps_only_this_device_merges_the_description_and_stops_at_six() -> None:
    entries = [
        SsdpEntry(IP, f"http://{IP}:80/{n}.xml", "Roku/9", f"uuid:{n}", ("upnp:rootdevice",))
        for n in range(8)
    ]
    entries.append(SsdpEntry("192.0.2.99", "http://192.0.2.99/x.xml", "Other", "uuid:x", ()))
    probes = FakeServiceProbes(ssdp=entries, upnp={IP: {"friendlyName": "Roku TV", "manufacturer": "Roku"}})
    found = ssdp_info(probes, IP)
    assert len(found) == 6
    assert found[0] == {
        "server": "Roku/9",
        "location": f"http://{IP}:80/0.xml",
        "st": ["upnp:rootdevice"],
        "usn": "uuid:0",
        "friendlyName": "Roku TV",
        "manufacturer": "Roku",
    }
    assert ssdp_info(FakeServiceProbes(), IP) == []


# ---------------------------------------------------------------- inspect


def test_a_full_inspection_returns_the_sections_in_order_and_keeps_hostile_text_raw() -> None:
    net = ScanNetwork(
        open_ports=(80,), closed=(22,), replies={IP: PingResult(2.5, 64)}, arp={IP: "a8:bb:cc:00:00:01"}
    )
    probes = FakeServiceProbes(
        http={(IP, 80): http(title="<script>x</script>")},
        banners={(IP, 80): b""},
        rdns={IP: "tv.lan"},
    )
    plugin, _ = make_plugin(net, probes, vendors=FakeVendors({"a8:bb:cc:00:00:01": "Roku, Inc"}))
    sections = inspect(plugin, "22,80")
    assert list(sections) == ["summary", "identity", "web", "ports", "discovery"]
    assert [s.title for s in sections.values()] == [
        "What it probably is",
        "Identity",
        "Web interfaces",
        "Open TCP ports",
        "Discovery protocols",
    ]
    assert {s.plugin_id for s in sections.values()} == {InspectionPlugin.manifest.guid}
    web = sections["web"].data["items"][0]
    assert web["title"] == "<script>x</script>"
    assert (web["port"], web["status"], web["url"]) == (80, 200, f"http://{IP}/")
    ports = sections["ports"].data
    assert (ports["ports_spec"], ports["scanned"], ports["refused"], ports["no_answer"]) == ("22,80", 2, 1, 0)
    assert [p["port"] for p in ports["open"]] == [80]
    assert ports["open"][0]["http"]["title"] == "<script>x</script>"
    identity = sections["identity"].data
    assert identity["mac"] == "a8:bb:cc:00:00:01" and identity["vendor"] == "Roku, Inc"
    assert (identity["rtt_ms"], identity["ttl"], identity["private_mac"]) == (2.5, 64, False)
    assert identity["names"] == ["tv.lan"]
    assert sections["summary"].data["device_name"] == "tv.lan"
    assert sections["summary"].data["name_source"] == "DNS"
    assert sections["discovery"].data["text"] == ["No answer to mDNS, UPnP/SSDP or NetBIOS."]
    for s in sections.values():
        assert isinstance(s.data["text"], list) and all(isinstance(t, str) for t in s.data["text"])
        assert not any("·" in t for t in s.data["text"])
        json.dumps(dict(s.data))


def test_the_optional_sections_appear_when_something_answers() -> None:
    rev = "10.2.0.192.in-addr.arpa"
    probes = FakeServiceProbes(
        mdns={(IP, rev): [DnsRecord(rev, 12, "den-tv.local.")]},
        ssdp=[SsdpEntry(IP, f"http://{IP}/d.xml", "Roku/9", "uuid:1", ())],
        upnp={IP: {"friendlyName": "Roku TV"}},
        netbios={IP: NetbiosInfo("ROKU", "WORKGROUP", (NetbiosName("ROKU", 0, False),), "")},
    )
    plugin, _ = make_plugin(ScanNetwork(), probes)
    sections = inspect(plugin, "22")
    assert list(sections) == ["summary", "identity", "ports", "mdns", "upnp"]
    assert sections["mdns"].data["hostname"] == "den-tv.local."
    assert sections["upnp"].data["entries"][0]["friendlyName"] == "Roku TV"
    assert sections["identity"].data["netbios"]["workgroup"] == "WORKGROUP"
    assert any("NetBIOS ROKU" in line for line in sections["identity"].data["text"])
    assert sections["summary"].data["device_name"] == "Roku TV"


def test_netbios_alone_is_enough_to_skip_the_discovery_section() -> None:
    probes = FakeServiceProbes(netbios={IP: NetbiosInfo("R720", "", (), "")})
    plugin, _ = make_plugin(ScanNetwork(), probes)
    assert "discovery" not in inspect(plugin, "22")


def test_a_private_mac_is_named_as_such_and_the_mac_falls_back_to_the_arp_table() -> None:
    net = ScanNetwork(arp={IP: "02:00:00:00:00:09"})
    plugin, _ = make_plugin(net)
    identity = inspect(plugin, "22")["identity"].data
    assert identity["mac"] == "02:00:00:00:00:09"
    assert identity["private_mac"] is True
    assert identity["vendor"] == "Random or local MAC"


def test_the_mac_comes_from_the_known_device_first() -> None:
    net = ScanNetwork(arp={IP: "a8:bb:cc:00:00:99"})
    plugin, _ = make_plugin(net, known=device(mac="a8:bb:cc:00:00:01"))
    assert inspect(plugin, "22")["identity"].data["mac"] == "a8:bb:cc:00:00:01"


def test_the_port_scan_uses_the_configured_timeouts_and_the_full_scan_timeout_above_5000_ports() -> None:
    net = ScanNetwork()
    plugin, _ = make_plugin(net, settings=InspectionSettings(port_timeout_s=0.7, full_scan_timeout_s=0.4))
    inspect(plugin, "1-100")
    assert net.timeouts == {0.7}
    big = ScanNetwork()
    plugin, _ = make_plugin(big, settings=InspectionSettings(port_timeout_s=0.7, full_scan_timeout_s=0.4))
    inspect(plugin, "1-5001")
    assert big.timeouts == {0.4}
    assert big.probed == 5001


def test_at_most_max_analyzed_open_ports_are_analyzed_but_all_are_listed() -> None:
    net = ScanNetwork(open_ports=(21, 22, 23, 25, 53))
    probes = CountingProbes(banners={(IP, p): b"hello" for p in (21, 22, 23, 25, 53)})
    plugin, _ = make_plugin(net, probes, settings=InspectionSettings(max_analyzed=2))
    ports = inspect(plugin, "20-60")["ports"].data
    assert [p["port"] for p in ports["open"]] == [21, 22, 23, 25, 53]
    assert probes.calls.count("banner") == 2
    assert [p.get("banner") for p in ports["open"]] == ["hello", "hello", None, None, None]
    assert [p.get("skipped", False) for p in ports["open"]] == [False, False, True, True, True]
    assert ports["no_answer"] == 41 - 5


def test_a_bad_ports_spec_raises_value_error() -> None:
    plugin, _ = make_plugin()
    with pytest.raises(ValueError):
        inspect(plugin, "0-5")


def test_a_probe_that_raises_does_not_stop_the_other_sections() -> None:
    class Broken(FakeServiceProbes):
        def reverse_dns(self, ip: str, timeout_s: float = 2.0) -> str:
            raise OSError("no resolver")

        def netbios(self, ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None:
            raise OSError("no socket")

    plugin, _ = make_plugin(ScanNetwork(), Broken())
    assert list(inspect(plugin, "22")) == ["summary", "identity", "ports", "discovery"]


def test_common_gives_only_the_ports_section_with_states_and_no_claims() -> None:
    net = ScanNetwork(open_ports=(80, 443), closed=(22,))
    probes = CountingProbes(http={(IP, 80): http()}, banners={(IP, 80): b""})
    plugin, ctx = make_plugin(net, probes, known=device())
    sections = inspect(plugin, "common")
    assert list(sections) == ["ports"]
    data = sections["ports"].data
    assert [p["port"] for p in data["open"]] == [80, 443]
    assert all("http" not in p and "banner" not in p for p in data["open"])
    assert all(p["skipped"] for p in data["open"])  # the quick probe never read a greeting
    assert "not analyzed" in "\n".join(data["text"])
    assert {s["port"]: s["state"] for s in data["states"]}[22] == "closed"
    assert data["scanned"] == 19
    assert probes.calls == []
    ctx.core.claim.assert_not_called()
    assert client(plugin).get("/open-ports").json() == {}


# ---------------------------------------------------------------- claims


def claims_of(ctx: Any) -> list[Any]:
    [call] = ctx.core.claim.call_args_list
    return list(call.args[0])


def test_claims_reach_the_core_for_a_known_device() -> None:
    net = ScanNetwork(open_ports=(8006,))
    probes = FakeServiceProbes(
        ssdp=[SsdpEntry(IP, f"http://{IP}/d.xml", "x", "u", ())],
        upnp={IP: {"friendlyName": "x" * 100}},
    )
    plugin, ctx = make_plugin(net, probes, known=device())
    inspect(plugin, "8006")
    items = claims_of(ctx)
    [name] = [i for i in items if isinstance(i, NameClaim)]
    assert (name.key, name.source, name.rank, name.checked_ms) == (f"k-{IP}", "UPnP", 6, NOW)
    assert name.name == "x" * 80
    [kind] = [i for i in items if isinstance(i, TypeClaim)]
    assert kind == TypeClaim(f"k-{IP}", "Proxmox host", "from inspection", "inspection", NOW)
    hints = [i for i in items if isinstance(i, Hint)]
    assert hints and {h.source for h in hints} == {"inspection"} and {h.key for h in hints} == {f"k-{IP}"}
    assert any(h.text == "Proxmox VE host (web UI on 8006)." for h in hints)


def test_no_claims_for_this_device_or_an_unknown_address() -> None:
    plugin, ctx = make_plugin(ScanNetwork(open_ports=(22,)), known=device(is_self=True))
    inspect(plugin, "22")
    ctx.core.claim.assert_not_called()
    plugin, ctx = make_plugin(ScanNetwork(open_ports=(22,)), known=None)
    inspect(plugin, "22")
    ctx.core.claim.assert_not_called()


def test_a_failing_claim_does_not_lose_the_report() -> None:
    plugin, ctx = make_plugin(ScanNetwork(open_ports=(22,)), known=device())
    ctx.core.claim.side_effect = RuntimeError("database is locked")
    assert "ports" in inspect(plugin, "22")


# ---------------------------------------------------------------- router


def client(plugin: InspectionPlugin) -> TestClient:
    api = FastAPI()
    api.include_router(plugin.router())
    return TestClient(api)


def test_open_ports_route_lists_what_was_found_per_inspected_known_device() -> None:
    net = ScanNetwork(open_ports=(22, 8006))
    plugin, _ = make_plugin(net, known=device())
    assert client(plugin).get("/open-ports").json() == {}
    inspect(plugin, "22,80,8006")
    assert client(plugin).get("/open-ports").json() == {
        IP: [{"port": 22, "name": "SSH"}, {"port": 8006, "name": "Proxmox"}]
    }


def test_open_ports_records_an_empty_list_when_nothing_is_open() -> None:
    plugin, _ = make_plugin(ScanNetwork(), known=device())
    inspect(plugin, "22")
    assert client(plugin).get("/open-ports").json() == {IP: []}


# ---------------------------------------------------------------- through the core


def test_through_the_real_run_inspection_the_report_has_the_sections_in_order(env: HostEnv) -> None:
    net = ScanNetwork(open_ports=(80,), arp={IP: "a8:bb:cc:00:00:01"})
    probes = FakeServiceProbes(http={(IP, 80): http(title="<b>Home</b>")}, banners={(IP, 80): b""})
    plugin, _ = make_plugin(net, probes)
    env.registry.register("inspection", Capability.INSPECTION, plugin.providers()[Capability.INSPECTION])

    report = RunInspection(env.registry, env.uow, FakeClock())(IP, "22,80")

    assert [s.id for s in report.sections] == ["summary", "identity", "web", "ports", "discovery"]
    assert {s.error for s in report.sections} == {None}
    with env.uow() as uow:
        stored = uow.inspections.latest(IP)
    assert stored is not None
    web = next(s for s in stored.sections if s.id == "web")
    assert web.data["items"][0]["title"] == "<b>Home</b>"


def test_through_the_real_run_inspection_a_bad_spec_becomes_an_error_section(env: HostEnv) -> None:
    plugin, _ = make_plugin()
    env.registry.register("inspection", Capability.INSPECTION, plugin.providers()[Capability.INSPECTION])
    report = RunInspection(env.registry, env.uow, FakeClock())(IP, "0-5", store=False)
    [section] = report.sections
    assert section.id == "error" and "bad port range" in (section.error or "")


def test_netview_inspect_prints_each_sections_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    net = ScanNetwork(open_ports=(80,), closed=(22,), replies={IP: PingResult(1.5, 64)})
    probes = FakeServiceProbes(http={(IP, 80): http(title="Home")}, banners={(IP, 80): b""})
    monkeypatch.setattr(netview.bootstrap, "SystemNetworkTools", lambda: net)
    monkeypatch.setattr(netview.bootstrap, "SystemServiceProbes", lambda **kw: probes)
    monkeypatch.setattr(
        netview.bootstrap,
        "find_entry_points",
        lambda group="netview.plugins": [DiscoveredPlugin("test:inspection", InspectionPlugin, None)],
    )

    result = CliRunner().invoke(cli_app, ["inspect", IP, "--ports", "22,80", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    for title in (
        "What it probably is",
        "Identity",
        "Web interfaces",
        "Open TCP ports",
        "Discovery protocols",
    ):
        assert title in lines
    assert "  No answer to mDNS, UPnP/SSDP or NetBIOS." in lines
    assert any(
        line.startswith("  2 TCP ports") and "1 open, 1 refused, 0 no answer" in line for line in lines
    )
    assert any("80/tcp" in line and "Home" in line for line in lines)
    assert not any("{" in line for line in lines)  # text lines, not JSON dumps
