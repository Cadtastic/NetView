"""Scans a device's TCP ports and reads its web pages, certificates and discovery answers (LM 975-1015)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, TypeVar

from netview.plugins.builtin.inspection.analysis import analyze_port, mdns_info, ssdp_info
from netview.plugins.builtin.inspection.hints import device_hints, device_type, discovered_name
from netview.plugins.builtin.inspection.ports import ALL_PORT_NAMES, parse_ports
from netview.plugins.builtin.inspection.routes import build_router
from netview.plugins.builtin.inspection.sections import build_sections, ports_section
from netview.plugins.builtin.inspection.settings import InspectionSettings
from netview.sdk import (
    NAME_RANKS,
    Capability,
    DeviceView,
    Hint,
    NameClaim,
    NetbiosInfo,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    ReportSection,
    TypeClaim,
    UiContribution,
    os_hint,
)

T = TypeVar("T")

FULL_SCAN_PORTS = 5000  # above this many ports a scan is a full one: more workers, a shorter timeout (LM 985)
FULL_SCAN_WORKERS = 1024
ANALYSIS_WORKERS = 16
MAX_NAME = 80
RANDOM_MAC = "Random or local MAC"


class InspectionPlugin(Plugin):
    manifest = PluginManifest(
        id="inspection",
        name="Inspection",
        version="0.1.0",
        description="Scans a device's TCP ports and reads its web pages, certificates and discovery answers",
        guid="ac1dc07d-123c-4414-a4c8-72013d00f267",
        display_name="Inspection",
        plugin_type=PluginType.SOFTWARE,
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.INSPECTION, Capability.API, Capability.WEB_UI}),
        permissions=frozenset(
            {
                Permission.DEVICES_READ,
                Permission.NAMES_WRITE,
                Permission.TYPES_WRITE,
                Permission.NETWORK_PROBE,
                Permission.API,
                Permission.UI,
            }
        ),
    )
    settings_model = InspectionSettings

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        self._lock = threading.Lock()
        self._open_ports: dict[str, list[dict[str, Any]]] = {}

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._ctx = ctx

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.INSPECTION: self}

    def router(self) -> Any:
        return build_router(self.open_ports)

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")

    def open_ports(self) -> dict[str, list[dict[str, Any]]]:
        """``{ip: [{port, name}]}`` for every known device inspected since the server started."""
        with self._lock:
            return {ip: [dict(p) for p in ports] for ip, ports in self._open_ports.items()}

    # ---- InspectionProvider

    def inspect(self, ip: str, ports_spec: str) -> list[ReportSection]:
        ctx = self._require()
        settings: InspectionSettings = self.settings or InspectionSettings()
        ip = str(IPv4Address(ip))
        ports = parse_ports(ports_spec)
        started = time.monotonic()
        if ports_spec.strip().lower() == "common":
            return [self._common(ip, ports, settings, started)]

        with ThreadPoolExecutor(5) as pool:
            f_ping = pool.submit(self._safe, lambda: ctx.net.ping(ip, 1000), None)
            f_rdns = pool.submit(self._safe, lambda: ctx.probes.reverse_dns(ip), "")
            f_netbios = pool.submit(self._safe, lambda: ctx.probes.netbios(ip), None)
            f_mdns = pool.submit(self._safe, lambda: mdns_info(ctx.probes, ip), None)
            f_ssdp = pool.submit(self._safe, lambda: ssdp_info(ctx.probes, ip), [])
            states = self._scan(ip, ports, settings)
            open_numbers = [p for p, s in states if s == "open"]
            refused = sum(1 for _, s in states if s == "closed")
            open_ports = self._analyze(ip, open_numbers, settings)
            ping = f_ping.result()
            rdns = f_rdns.result()
            netbios = f_netbios.result()
            mdns = f_mdns.result()
            upnp = f_ssdp.result()

        device = self._device(ip)
        mac = (device.mac if device is not None and device.mac else None) or self._arp(ip)
        private_mac = _private_mac(mac)
        vendor = self._vendor(mac) or (RANDOM_MAC if private_mac else "")
        ttl = ping.ttl if ping is not None else None
        netbios_dict = _netbios_dict(netbios)
        names = [rdns, (netbios_dict or {}).get("name"), (mdns or {}).get("hostname")]
        names += [u.get("friendlyName") for u in upnp]
        r: dict[str, Any] = {
            "ip": ip,
            "ports_spec": ports_spec,
            "rtt": ping.rtt_ms if ping is not None else None,
            "ttl": ttl,
            "rdns": rdns,
            "netbios": netbios_dict,
            "mdns": mdns,
            "upnp": upnp,
            "mac": mac,
            "private_mac": private_mac,
            "vendor": vendor,
            "os_hint": os_hint(ttl),
            "ports": {
                "scanned": len(ports),
                "open": open_ports,
                "refused": refused,
                "no_answer": len(ports) - len(open_numbers) - refused,
            },
            "names": list(dict.fromkeys(n for n in names if n)),
        }
        r["hints"] = device_hints(r)
        r["device_name"], r["name_source"] = discovered_name(r)
        r["type"] = device_type(r)
        r["duration"] = round(time.monotonic() - started, 1)
        sections = build_sections(r)
        if device is not None and not device.is_self:
            self._learn(device, r, open_numbers)
        return sections

    # ---- the pieces

    def _common(
        self, ip: str, ports: list[int], settings: InspectionSettings, started: float
    ) -> ReportSection:
        """The quick probe: only the TCP state of the common ports. No banners, web pages or claims."""
        states = self._scan(ip, ports, settings)
        names = ALL_PORT_NAMES
        open_ports = [
            {"port": p, "name": names.get(p, ""), "skipped": True} for p, s in states if s == "open"
        ]
        refused = sum(1 for _, s in states if s == "closed")
        r = {
            "ports_spec": "common",
            "duration": round(time.monotonic() - started, 1),
            "ports": {
                "scanned": len(ports),
                "open": open_ports,
                "refused": refused,
                "no_answer": len(ports) - len(open_ports) - refused,
            },
        }
        listing = [{"port": p, "name": names.get(p, ""), "state": s} for p, s in states]
        return ports_section(r, listing)

    def _scan(self, ip: str, ports: list[int], settings: InspectionSettings) -> list[tuple[int, str]]:
        ctx = self._require()
        big = len(ports) > FULL_SCAN_PORTS
        timeout = settings.full_scan_timeout_s if big else settings.port_timeout_s
        workers = max(1, min(FULL_SCAN_WORKERS if big else settings.workers, len(ports)))

        def state(port: int) -> tuple[int, str]:
            try:
                return port, str(ctx.net.tcp_probe(ip, port, timeout).state)
            except Exception:
                return port, "filtered"

        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(state, ports))

    def _analyze(
        self, ip: str, open_numbers: list[int], settings: InspectionSettings
    ) -> list[dict[str, Any]]:
        """Read the first ``max_analyzed`` open ports; the others are listed with ``skipped`` set."""
        ctx = self._require()
        head, tail = open_numbers[: settings.max_analyzed], open_numbers[settings.max_analyzed :]

        def analyze(port: int) -> dict[str, Any]:
            try:
                return analyze_port(ctx.probes, ip, port)
            except Exception:
                ctx.log.debug("could not analyze %s:%s", ip, port, exc_info=True)
                return {"port": port, "name": ALL_PORT_NAMES.get(port, "")}

        with ThreadPoolExecutor(max(1, min(ANALYSIS_WORKERS, len(head)))) as pool:
            analyzed = list(pool.map(analyze, head))
        return analyzed + [{"port": p, "name": ALL_PORT_NAMES.get(p, ""), "skipped": True} for p in tail]

    def _learn(self, device: DeviceView, r: dict[str, Any], open_numbers: list[int]) -> None:
        """Tell the core what the inspection found out about a known device, and remember its open ports."""
        ctx = self._require()
        now = ctx.clock.now_ms()
        items: list[NameClaim | TypeClaim | Hint] = []
        if r["device_name"]:
            source = r["name_source"]
            items.append(NameClaim(device.key, r["device_name"][:MAX_NAME], source, NAME_RANKS[source], now))
        if r["type"]:
            items.append(TypeClaim(device.key, r["type"], "from inspection", "inspection", now))
        items += [Hint(device.key, text, "inspection") for text in r["hints"]]
        if items:
            try:
                ctx.core.claim(items)
            except Exception:
                ctx.log.warning("could not store what the inspection of %s found", r["ip"], exc_info=True)
        with self._lock:
            self._open_ports[r["ip"]] = [{"port": p, "name": ALL_PORT_NAMES.get(p, "")} for p in open_numbers]

    def _device(self, ip: str) -> DeviceView | None:
        ctx = self._require()
        try:
            device = ctx.core.device_by_ip(ip)
        except Exception:
            ctx.log.debug("could not look up %s", ip, exc_info=True)
            return None
        return device if isinstance(device, DeviceView) else None

    def _arp(self, ip: str) -> str | None:
        found = self._safe(lambda: self._require().net.arp_table().get(ip), None)
        return found or None

    def _vendor(self, mac: str | None) -> str:
        ctx = self._require()
        return str(self._safe(lambda: ctx.vendors.vendor(mac), "")) if mac else ""

    def _safe(self, fn: Callable[[], T], default: T) -> T:
        """Run one probe; a probe that raises counts as having found nothing."""
        try:
            return fn()
        except Exception:
            self._require().log.debug("probe failed", exc_info=True)
            return default

    def _require(self) -> PluginContext:
        if self._ctx is None:
            raise RuntimeError("inspection used before setup")
        return self._ctx


def _private_mac(mac: str | None) -> bool:
    """True for a locally administered address (the second bit of the first byte)."""
    try:
        return bool(mac and int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


def _netbios_dict(info: NetbiosInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "name": info.name,
        "workgroup": info.workgroup,
        "names": [{"name": n.name, "suffix": n.suffix, "group": n.group} for n in info.names],
        "mac": info.mac,
    }
