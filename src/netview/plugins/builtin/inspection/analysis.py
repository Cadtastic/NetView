"""What one open port, and one device's mDNS and UPnP answers, say (LM 561-590, 669-688, 794-799)."""

import re
from dataclasses import asdict
from typing import Any

from netview.plugins.builtin.inspection.ports import ALL_PORT_NAMES, TLS_FIRST
from netview.sdk import HttpProbe, ServiceProbes

GRPC_BANNER = "HTTP/2 without TLS (server sent SETTINGS first): usually a gRPC API"
MDNS_SERVICES = "_services._dns-sd._udp.local"
_UNPRINTABLE = re.compile(r"[^\x20-\x7e\t]+")
# TXT keys that are identifiers or opaque blobs, not something a person can read (LM 683)
_HIDDEN_TXT = frozenset(
    ("pk", "pi", "psi", "gid", "deviceid", "id", "bs", "rpba", "rpad", "rpfl", "rphn", "rpmac", "rpvr", "cd")
)
MAX_TXT = 16
MAX_SERVICE_TYPES = 8
MAX_INSTANCES = 6
MAX_SSDP = 6


def http_dict(probe: HttpProbe) -> dict[str, Any]:
    """An ``HttpProbe`` as plain JSON-ready data."""
    out = asdict(probe)
    if out.get("cert") is not None:
        out["cert"]["san"] = list(out["cert"].get("san") or ())
    return out


def analyze_port(probes: ServiceProbes, ip: str, port: int) -> dict[str, Any]:
    """Read a greeting from ``ip:port``, else ask for ``/`` over plain HTTP and TLS (order set by port)."""
    info: dict[str, Any] = {"port": port, "name": ALL_PORT_NAMES.get(port, "")}
    try:
        banner = probes.tcp_banner(ip, port)
    except Exception:
        banner = None
    if banner is None:
        return info
    if len(banner) >= 9 and banner[3] == 0x04 and banner[4] in (0, 1) and banner[5:9] == b"\0\0\0\0":
        info["banner"] = GRPC_BANNER
        return info
    if banner and not banner.startswith(b"HTTP/"):
        text = _UNPRINTABLE.sub(" ", banner.decode("utf-8", errors="replace")).strip()[:160]
        if text:
            info["banner"] = text
            return info
    for use_tls in (True, False) if port in TLS_FIRST else (False, True):
        try:
            probe = probes.http_probe(ip, port, use_tls)
        except Exception:
            probe = None
        if probe is not None:
            info["http"] = http_dict(probe)
            if probe.status or use_tls:
                return info
    return info


def _txt_pairs(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def mdns_info(probes: ServiceProbes, ip: str) -> dict[str, Any] | None:
    """The host name and Bonjour services ``ip`` announces over mDNS; ``None`` when it answers nothing."""
    rev = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    host = next((str(r.value) for r in probes.mdns_query(ip, rev) if r.rtype == 12 and r.value), "")
    records = probes.mdns_query(ip, MDNS_SERVICES)
    types = sorted(
        {str(r.value) for r in records if r.rtype == 12 and r.value and r.name.startswith("_services")}
    )[:MAX_SERVICE_TYPES]
    services: list[dict[str, Any]] = []
    for st in types:
        rr = probes.mdns_query(ip, st, timeout_s=0.9)
        instances = sorted({str(r.value) for r in rr if r.rtype == 12 and r.value and r.name == st})
        txt: dict[str, str] = {}
        for r in rr:
            if r.rtype != 16:
                continue
            for kv in _txt_pairs(r.value):
                key, _, val = kv.partition("=")
                if key and len(txt) < MAX_TXT and key.lower() not in _HIDDEN_TXT:
                    txt[key] = val[:80]
        services.append(
            {"type": st, "instances": [i.split("." + st)[0] for i in instances][:MAX_INSTANCES], "txt": txt}
        )
        if not host:
            host = next((r.name for r in rr if r.rtype == 1 and r.value == ip), "")
    return {"hostname": host, "services": services} if host or services else None


def ssdp_info(probes: ServiceProbes, ip: str, timeout_s: float = 2.5) -> list[dict[str, Any]]:
    """What ``ip`` says to a UPnP search, each answer with its device description merged in; at most six."""
    out: list[dict[str, Any]] = []
    for entry in probes.ssdp_search(ip, timeout_s):
        if entry.ip != ip:
            continue
        item: dict[str, Any] = {
            "server": entry.server,
            "location": entry.location,
            "st": list(entry.st),
            "usn": entry.usn,
        }
        item.update(probes.upnp_description(ip, entry.location))
        out.append(item)
    return out[:MAX_SSDP]
