from netview.application.ports.probes import (
    CertInfo,
    DnsRecord,
    HttpProbe,
    NetbiosInfo,
    NetbiosName,
    SsdpEntry,
)
from netview.application.ports.system import TcpSocket, WifiInfo
from netview.sdk.testing.contract import _FakeContext
from netview.sdk.testing.fakes import FakeServiceProbes, FakeSystemInfo

IP = "192.168.1.9"


def test_probe_dataclasses_are_frozen_with_the_documented_defaults() -> None:
    cert = CertInfo("ab")
    assert (cert.subject, cert.self_signed, cert.san) == ("", False, ())
    assert NetbiosInfo("PC", "WORKGROUP", (NetbiosName("PC", 0, False),), "aa:bb:cc:dd:ee:ff").name == "PC"
    assert DnsRecord("x.local", 1, "192.0.2.1").value == "192.0.2.1"
    assert SsdpEntry(IP, "http://x/", "srv", "usn", ("a",)).st == ("a",)
    http = HttpProbe("http", "http://x/", 200, "OK", "", "", "", "t", "", "", "", None, None)
    assert http.cert is None


def test_fake_probes_return_canned_answers_and_empties_otherwise() -> None:
    http = HttpProbe(
        "https", f"https://{IP}/", 401, "Unauthorized", "", "", "", "", "", "Basic", "iDRAC", "TLSv1.2", None
    )
    entry = SsdpEntry(IP, f"http://{IP}:80/d.xml", "srv", "usn", ("upnp:rootdevice",))
    probes = FakeServiceProbes(
        rdns={IP: "host.lan"},
        netbios={IP: NetbiosInfo("PC", "WG", (), "")},
        mdns={(IP, "x.local"): [DnsRecord("x.local", 1, "192.0.2.1")]},
        ssdp=[entry],
        upnp={IP: {"friendlyName": "Box"}},
        http={(IP, 443): http},
        banners={(IP, 22): b"SSH-2.0"},
    )
    assert probes.reverse_dns(IP) == "host.lan" and probes.reverse_dns("192.0.2.1") == ""
    assert probes.netbios(IP) is not None and probes.netbios("192.0.2.1") is None
    assert probes.mdns_query(IP, "x.local")[0].value == "192.0.2.1"
    assert probes.mdns_query(IP, "other.local") == []
    assert probes.ssdp_search() == [entry]
    assert probes.upnp_description(IP, entry.location) == {"friendlyName": "Box"}
    assert probes.upnp_description("192.0.2.1", "http://x/") == {}
    assert probes.http_probe(IP, 443, True) is http and probes.http_probe(IP, 80, False) is None
    assert probes.tcp_banner(IP, 22) == b"SSH-2.0" and probes.tcp_banner(IP, 23) is None


def test_default_fake_probes_know_nothing() -> None:
    probes = FakeServiceProbes()
    assert probes.reverse_dns(IP) == "" and probes.netbios(IP) is None
    assert probes.ssdp_search() == [] and probes.tcp_banner(IP, 1) is None


def test_fake_system_info() -> None:
    sock = TcpSocket("192.168.1.2", 50000, IP, 443, "ESTABLISHED", "chrome.exe")
    wifi = WifiInfo(ssid="home", signal_pct=70)
    system = FakeSystemInfo(interface_bytes=(10, 20), wifi=wifi, sockets=[sock])
    assert system.interface_bytes() == (10, 20)
    assert system.wifi() == WifiInfo(ssid="home", signal_pct=70)
    assert system.tcp_sockets() == [sock]
    empty = FakeSystemInfo()
    assert empty.interface_bytes() is None and empty.wifi() is None and empty.tcp_sockets() == []


def test_fake_system_info_steps_through_a_sequence_of_readings_and_repeats_the_last() -> None:
    system = FakeSystemInfo(interface_bytes=[(1000, 500), (6000, 1500), (10, 10)])
    assert [system.interface_bytes() for _ in range(5)] == [
        (1000, 500),
        (6000, 1500),
        (10, 10),
        (10, 10),
        (10, 10),
    ]
    assert FakeSystemInfo(interface_bytes=[]).interface_bytes() is None
    mixed = FakeSystemInfo(interface_bytes=[None, (1, 2)])
    assert [mixed.interface_bytes() for _ in range(3)] == [None, (1, 2), (1, 2)]
    single = FakeSystemInfo(interface_bytes=(7, 8))
    assert [single.interface_bytes() for _ in range(3)] == [(7, 8)] * 3
    pair_of_pairs = FakeSystemInfo(interface_bytes=((1, 2), (3, 4)))
    assert [pair_of_pairs.interface_bytes() for _ in range(3)] == [(1, 2), (3, 4), (3, 4)]


def test_the_fake_plugin_context_exposes_both() -> None:
    ctx = _FakeContext("x", None)
    assert isinstance(ctx.probes, FakeServiceProbes)
    assert isinstance(ctx.system, FakeSystemInfo)
