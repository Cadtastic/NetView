"""The pure inspection helpers: port lists, hints, device type and the discovered name."""

from typing import Any

import pytest

from netview.plugins.builtin.inspection.hints import device_hints, device_type, discovered_name
from netview.plugins.builtin.inspection.ports import (
    ALL_PORT_NAMES,
    COMMON_PORTS,
    DEEP_PORTS,
    LOW_NAMES,
    TLS_FIRST,
    parse_ports,
)


def result(open_ports: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """A result dict shaped like the old LAN monitor's ``inspect_host`` result."""
    r: dict[str, Any] = {
        "ports": {"scanned": 1100, "open": open_ports or [], "refused": 0, "no_answer": 1100},
        "mdns": None,
        "upnp": [],
        "netbios": None,
        "rdns": "",
        "names": [],
        "vendor": "",
        "ttl": None,
        "private_mac": False,
    }
    r.update(extra)
    return r


def cert(issuer: str = "", issuer_org: str = "", subject: str = "") -> dict[str, Any]:
    return {"subject": subject, "issuer": issuer, "issuer_org": issuer_org, "self_signed": False, "san": []}


def web_port(port: int, **http: Any) -> dict[str, Any]:
    return {"port": port, "name": "", "http": {"scheme": "https", "status": 200, **http}}


AIRPLAY_LG = {
    "hostname": "lg-tv.local",
    "services": [
        {
            "type": "_airplay._tcp.local",
            "instances": ["LG TV"],
            "txt": {"manufacturer": "LG", "model": "OLED"},
        }
    ],
}


# ---------------------------------------------------------------- ports


def test_the_port_tables_are_copied_whole() -> None:
    assert len(COMMON_PORTS) == 19
    assert COMMON_PORTS[0] == (22, "SSH")
    assert 62078 in DEEP_PORTS and DEEP_PORTS[8006] == "Proxmox"
    assert LOW_NAMES[445] == "SMB"
    assert {443, 8006, 16993} <= TLS_FIRST
    assert ALL_PORT_NAMES[22] == "SSH" and ALL_PORT_NAMES[9100] == "Printer (JetDirect)"


def test_parse_ports_top_is_the_first_1024_plus_the_deep_ports_sorted() -> None:
    ports = parse_ports("top")
    assert ports == sorted(ports)
    assert len(ports) == 1024 + len([p for p in DEEP_PORTS if p > 1024])


def test_parse_ports_common_is_the_common_list() -> None:
    assert parse_ports("common") == [p for p, _ in COMMON_PORTS]


def test_parse_ports_all_lists_every_port() -> None:
    assert parse_ports("all") == list(range(1, 65536))


def test_parse_ports_lists_and_ranges() -> None:
    assert parse_ports(" 80, 22,8000-8002 ,80") == [22, 80, 8000, 8001, 8002]
    assert parse_ports(None) == parse_ports("top")  # type: ignore[arg-type]
    assert parse_ports("1-") == [1]  # an open range ends where it starts, as in the old tool


@pytest.mark.parametrize("spec", ["0-5", "65536", "5-2", "x", ","])
def test_parse_ports_rejects_bad_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_ports(spec)


# ---------------------------------------------------------------- hints


def test_an_airplay_receiver_by_another_maker_gets_the_non_apple_hint_and_no_apple_hint() -> None:
    r = result(
        mdns=AIRPLAY_LG,
        upnp=[{"friendlyName": "LG TV", "manufacturer": "", "modelName": ""}],
    )
    hints = device_hints(r)
    assert hints[0] == "It identifies itself as LG TV (LG OLED)."
    assert "Accepts AirPlay from Apple devices (built into this LG device)." in hints
    assert not [h for h in hints if h.startswith("Apple device")]


def test_an_airplay_receiver_made_by_apple_gets_the_apple_hint() -> None:
    r = result(
        mdns={
            "hostname": "",
            "services": [
                {"type": "_airplay._tcp.local", "instances": ["Den"], "txt": {"manufacturer": "Apple"}}
            ],
        }
    )
    hints = device_hints(r)
    assert hints[0] == "It identifies itself as a device (Apple)."
    assert any(h.startswith("Apple device (AirPlay / companion-link") for h in hints)
    assert not any(h.startswith("Accepts AirPlay") for h in hints)


def test_the_self_identification_hint_comes_first_even_when_a_later_rule_matches() -> None:
    r = result(
        [{"port": 23, "name": "Telnet"}], upnp=[{"friendlyName": "Hall printer", "manufacturer": "Acme"}]
    )
    hints = device_hints(r)
    assert hints[0] == "It identifies itself as Hall printer (Acme)."
    assert "Telnet is open: an old or embedded device. Telnet sends passwords in clear text." in hints


def test_the_iphone_port_gives_the_iphone_hint() -> None:
    r = result([{"port": 62078, "name": "Apple lockdown (iPhone/iPad)"}])
    assert any(h.startswith("Apple iPhone or iPad") for h in device_hints(r))
    assert device_type(r) == "iPhone or iPad"


def test_a_spacex_certificate_gives_the_starlink_type_and_hint() -> None:
    c = cert(issuer="SpaceX Router CA", issuer_org="SpaceX", subject="Router-0100")
    r = result([web_port(443, cert=c)])
    assert device_type(r) == "Starlink router"
    hints = device_hints(r)
    assert (
        "Starlink router or mesh node: its TLS certificate 'Router-0100' was issued by SpaceX Router CA."
        in hints
    )


def test_a_page_that_says_starlink_without_a_spacex_certificate_gives_the_page_hint() -> None:
    r = result([web_port(80, scheme="http", title="Starlink")])
    assert "Starlink equipment (the web page says Starlink)." in device_hints(r)


def test_no_open_port_and_nothing_refused_says_a_firewall_drops_everything() -> None:
    hints = device_hints(result())
    assert any(h.startswith("No TCP port answered at all") for h in hints)


def test_no_open_port_but_refusals_says_the_device_is_there() -> None:
    r = result()
    r["ports"]["refused"] = 40
    assert any(h.startswith("No open ports among those scanned") for h in device_hints(r))


def test_the_vendor_fallback_and_the_ttl_and_private_mac_lines() -> None:
    r = result(vendor="Amazon Technologies", ttl=64, private_mac=True)
    hints = device_hints(r)
    assert hints[0].startswith("Amazon device: an Echo")
    assert any(
        h.startswith("Its MAC address is locally administered") and "most likely a virtual" in h
        for h in hints
    )
    assert hints[-1] == "Ping TTL 64 suggests Linux/Apple/Android/embedded."


def test_the_device_type_falls_back_to_the_vendor_type() -> None:
    assert device_type(result(vendor="Raspberry Pi Trading Ltd")) == "Raspberry Pi"
    assert device_type(result(vendor="", ttl=128)) == "Windows PC"
    assert device_type(result()) == ""


def test_the_device_type_prefers_proxmox_and_printers() -> None:
    assert device_type(result([{"port": 8006, "name": ""}])) == "Proxmox host"
    assert device_type(result([{"port": 9100, "name": ""}])) == "Printer"


# ---------------------------------------------------------------- discovered name


def test_the_upnp_name_wins_over_everything() -> None:
    r = result(
        upnp=[{"friendlyName": "Roku TV"}],
        netbios={"name": "ROKU"},
        mdns={"hostname": "roku.local.", "services": []},
        rdns="roku.lan",
    )
    assert discovered_name(r) == ("Roku TV", "UPnP")


def test_name_sources_in_order_with_local_stripped() -> None:
    airplay = {
        "hostname": "x.local",
        "services": [{"type": "_airplay._tcp.local", "instances": ["Den TV"], "txt": {}}],
    }
    assert discovered_name(result(mdns=airplay)) == ("Den TV", "AirPlay")
    assert discovered_name(result(netbios={"name": "R720"})) == ("R720", "NetBIOS")
    assert discovered_name(result(mdns={"hostname": "jessis-ipad.local.", "services": []})) == (
        "jessis-ipad",
        "mDNS",
    )
    rdp = {"port": 3389, "name": "RDP", "http": {"scheme": "https", "cert": cert(subject="DESKTOP-7")}}
    assert discovered_name(result([rdp])) == ("DESKTOP-7", "RDP certificate")
    assert discovered_name(result(rdns="printer.lan")) == ("printer.lan", "DNS")
    assert discovered_name(result()) == ("", "")
