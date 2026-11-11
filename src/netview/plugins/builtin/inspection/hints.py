"""What an inspection result says about a device: its own name, its type and plain-language hints.

These are pure functions over a plain result dict shaped like the old LAN monitor's ``inspect_host`` result
(LM 817-827, 847-870 and 888-972): ``ports`` (``open`` entries with optional ``http``, and ``refused``),
``mdns``, ``upnp`` (a list), ``netbios``, ``rdns``, ``names``, ``vendor``, ``ttl`` and ``private_mac``.
"""

import re
from typing import Any

from netview.sdk import os_hint, vendor_type


def _open(r: dict[str, Any]) -> list[dict[str, Any]]:
    return list((r.get("ports") or {}).get("open") or [])


def _http(p: dict[str, Any]) -> dict[str, Any]:
    return p.get("http") or {}


def _cert(p: dict[str, Any]) -> dict[str, Any]:
    return _http(p).get("cert") or {}


def _services(r: dict[str, Any]) -> list[dict[str, Any]]:
    return list((r.get("mdns") or {}).get("services") or [])


def _upnp(r: dict[str, Any]) -> list[dict[str, Any]]:
    return list(r.get("upnp") or [])


def discovered_name(r: dict[str, Any]) -> tuple[str, str]:
    """The best name the device gave for itself: ``(name, source)``, or ``("", "")``."""
    rdp = next((_cert(p).get("subject") for p in _open(r) if p["port"] == 3389 and p.get("http")), "")
    airplay = next(
        (s["instances"][0] for s in _services(r) if s["type"].startswith("_airplay") and s["instances"]), ""
    )
    host = re.sub(r"\.local\.?$", "", (r.get("mdns") or {}).get("hostname", ""))
    candidates = [
        (next((u.get("friendlyName") for u in _upnp(r) if u.get("friendlyName")), ""), "UPnP"),
        (airplay, "AirPlay"),
        ((r.get("netbios") or {}).get("name", ""), "NetBIOS"),
        (host, "mDNS"),
        (rdp, "RDP certificate"),
        (r.get("rdns", ""), "DNS"),
    ]
    return next(((str(n), s) for n, s in candidates if n), ("", ""))


def device_type(r: dict[str, Any]) -> str:
    """A short type label from an inspection result, else from the maker of the MAC address."""
    ports = {p["port"] for p in _open(r)}
    svc = " ".join(s["type"] for s in _services(r))
    certs = " ".join(str(_http(p).get("cert") or "") for p in _open(r)).lower()
    fname = " ".join(u.get("friendlyName", "") + " " + u.get("deviceType", "") for u in _upnp(r)).lower()
    names = " ".join(r.get("names") or []).lower()
    rules = (
        ("spacex" in certs, "Starlink router"),
        ("idrac" in certs or "idrac" in fname, "Dell iDRAC"),
        (8006 in ports, "Proxmox host"),
        ("roku" in fname and " tv" in fname, "Roku TV"),
        ("roku" in fname or 8060 in ports, "Roku player"),
        ("_googlecast" in svc or {8008, 8009} <= ports, "Cast device"),
        (62078 in ports or "_apple-mobdev2" in svc, "iPhone or iPad"),
        ("_companion-link" in svc, "Apple device"),
        ("android" in names, "Android phone or tablet"),
        (bool({9100, 631, 515} & ports) or "_ipp" in svc, "Printer"),
        (8123 in ports, "Home Assistant"),
        (3389 in ports or bool({135, 445} & ports), "Windows PC"),
    )
    for cond, kind in rules:
        if cond:
            return kind
    return vendor_type(r.get("vendor") or "", r.get("ttl"), bool(r.get("private_mac")))


def device_hints(r: dict[str, Any]) -> list[str]:
    """Plain-language guesses about what the device is, the strongest first."""
    hints: list[str] = []
    open_ports = _open(r)
    ports = {p["port"] for p in open_ports}
    svc = " ".join(s["type"] for s in _services(r))
    upnp = " ".join(
        f"{u.get('manufacturer', '')} {u.get('modelName', '')} {u.get('server', '')}" for u in _upnp(r)
    )
    web = " ".join(
        f"{_http(p).get('title', '')} {_http(p).get('server', '')} {_cert(p).get('subject', '')} "
        f"{_cert(p).get('issuer', '')} {_cert(p).get('issuer_org', '')}"
        for p in open_ports
    ).lower()
    certs = [_cert(p) for p in open_ports if _cert(p)]
    spacex = next(
        (c for c in certs if "spacex" in f"{c.get('issuer', '')} {c.get('issuer_org', '')}".lower()), None
    )
    # A device that names itself (UPnP description or AirPlay TXT) beats every guess below.
    airplay_txt: dict[str, str] = next(
        (s["txt"] for s in _services(r) if s["type"].startswith("_airplay")), {}
    )
    maker = next((u.get("manufacturer") for u in _upnp(r) if u.get("manufacturer")), "") or airplay_txt.get(
        "manufacturer", ""
    )
    model = next((u.get("modelName") for u in _upnp(r) if u.get("modelName")), "") or airplay_txt.get(
        "model", ""
    )
    fname = next((u.get("friendlyName") for u in _upnp(r) if u.get("friendlyName")), "")
    if fname or maker:
        made = f" ({' '.join(x for x in (maker, model) if x)})" if maker or model else ""
        hints.append(f"It identifies itself as {fname or 'a device'}{made}.")
    apple_made = not maker or maker.lower().startswith("apple")
    airplay = "_airplay" in svc or "_raop" in svc
    rdp_cert = next((_cert(p) for p in open_ports if p["port"] == 3389 and _cert(p).get("subject")), None)
    if rdp_cert:
        hints.append(f"Windows PC named {rdp_cert['subject']} (from its Remote Desktop certificate).")
    rules = [
        (
            any("android" in n.lower() for n in r.get("names") or []),
            "Android phone or tablet (from the name it announces over mDNS).",
        ),
        (
            62078 in ports or "_apple-mobdev2" in svc,
            "Apple iPhone or iPad (Apple's device-sync port 62078 or Bonjour mobile-device service).",
        ),
        (
            ("_companion-link" in svc or airplay) and apple_made,
            "Apple device (AirPlay / companion-link Bonjour services): "
            "Mac, Apple TV, HomePod, iPhone or iPad.",
        ),
        (airplay and not apple_made, f"Accepts AirPlay from Apple devices (built into this {maker} device)."),
        (
            "_googlecast" in svc or {8008, 8009} <= ports,
            "Google Cast device (Chromecast, Google TV, Nest speaker or a TV with Cast built in).",
        ),
        (
            8060 in ports or "roku" in upnp.lower(),
            "Roku streaming device or Roku TV (port 8060 is Roku's control API).",
        ),
        (8006 in ports or "proxmox" in web, "Proxmox VE host (web UI on 8006)."),
        ("idrac" in web or "integrated dell remote access" in web, "Dell iDRAC management controller."),
        (bool({9100, 631, 515} & ports) or "_ipp" in svc or "_printer" in svc, "Printer or scanner."),
        (bool({135, 139, 445} & ports) and 3389 in ports, "Windows PC with Remote Desktop on."),
        (bool({135, 445} & ports) and 3389 not in ports, "Windows PC or a NAS sharing files (SMB)."),
        (5555 in ports, "Android device with network debugging (ADB) open: turn that off unless you use it."),
        (32400 in ports, "Plex Media Server."),
        (8123 in ports, "Home Assistant."),
        (bool({8443, 8880, 8843} & ports) and "unifi" in web, "Ubiquiti UniFi controller or device."),
        (
            bool(spacex),
            f"Starlink router or mesh node: its TLS certificate '{(spacex or {}).get('subject', '')}' "
            "was issued by SpaceX Router CA.",
        ),
        ("starlink" in web and not spacex, "Starlink equipment (the web page says Starlink)."),
        ("netgear" in web or "netgear" in upnp.lower(), "NETGEAR device."),
        ("synology" in web or (5001 in ports and "synology" in upnp.lower()), "Synology NAS."),
        ("_hap" in svc, "Apple HomeKit accessory."),
        ("_spotify-connect" in svc, "Speaker or app that supports Spotify Connect."),
        ("_amzn" in svc or "amazon" in upnp.lower(), "Amazon device (Echo, Fire TV or Kindle)."),
        ("samsung" in upnp.lower() or "samsung" in web, "Samsung device (often a TV or phone)."),
        ("lg" in upnp.lower().split() or "webos" in upnp.lower(), "LG TV (webOS)."),
        ("sonos" in upnp.lower() or "_sonos" in svc, "Sonos speaker."),
        (23 in ports, "Telnet is open: an old or embedded device. Telnet sends passwords in clear text."),
    ]
    hints += [text for cond, text in rules if cond]
    vendor = (r.get("vendor") or "").lower()
    if not hints:  # fall back to what the maker of the MAC address usually builds
        for key, text in (
            ("amazon", "Amazon device: an Echo, Fire TV, Kindle or Ring. They keep every port closed."),
            (
                "altobeam",
                "A budget smart-home gadget (camera, doorbell, smart plug or TV box): "
                "AltoBeam makes the Wi-Fi chip, and these talk only to their cloud.",
            ),
            (
                "tpv display",
                "A TV or monitor made by TPV (Philips, AOC and several store brands). "
                "Silent like this, it's probably in standby.",
            ),
            ("intel", "A PC or laptop (Intel network adapter)."),
            ("raspberry", "A Raspberry Pi."),
        ):
            if key in vendor:
                hints.append(text)
                break
    if 8000 in ports and "incredibuild" in web:
        hints.append("Runs the Incredibuild build agent (web page on port 8000).")
    strong = bool(hints)
    if r.get("private_mac"):
        hints.append(
            "Its MAC address is locally administered, so it doesn't name the manufacturer. "
            + (
                "Here that is most likely a virtual or mesh interface on the device identified above."
                if strong
                else "That's usually a phone, tablet or laptop using Wi-Fi privacy (a random address), "
                "but mesh Wi-Fi nodes and virtual machines use such addresses too."
            )
        )
    refused = (r.get("ports") or {}).get("refused", 0)
    if not ports and refused == 0:
        hints.append(
            "No TCP port answered at all, not even with a refusal: a firewall drops everything. "
            "That's normal for phones and tablets, and for Windows PCs on a network marked Public."
        )
    elif not ports:
        hints.append(
            "No open ports among those scanned, but the device refuses connections, so it is there "
            "and simply runs no services."
        )
    if r.get("ttl"):
        hints.append(f"Ping TTL {r['ttl']} suggests {os_hint(r['ttl'])}.")
    return hints
