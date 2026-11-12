"""Ping sweep plus ARP table discovery."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any

from netview.plugins.builtin.lan_discovery.routes import build_router
from netview.plugins.builtin.lan_discovery.settings import LanDiscoverySettings
from netview.sdk import (
    Capability,
    Permission,
    PingResult,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    Sighting,
    UiContribution,
)


class _Discovery:
    def __init__(self, plugin: LanDiscoveryPlugin, ctx: PluginContext) -> None:
        self._plugin = plugin
        self._ctx = ctx

    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]:
        ctx = self._ctx
        settings: LanDiscoverySettings = self._plugin.settings
        started = time.monotonic()
        ips = [str(h) for h in subnet.hosts()]

        def ping(ip: str) -> PingResult | None:
            try:
                return ctx.net.ping(ip, settings.ping_timeout_ms)
            except Exception:  # one bad probe must not abort the sweep
                ctx.log.debug("ping %s failed", ip, exc_info=True)
                return None

        with ThreadPoolExecutor(max_workers=settings.workers) as pool:
            replies = dict(zip(ips, pool.map(ping, ips), strict=True))
        try:
            arp = ctx.net.arp_table()
        except Exception:
            ctx.log.warning("could not read the ARP table", exc_info=True)
            arp = {}

        now = ctx.clock.now_ms()
        sightings: list[Sighting] = []
        replied = arp_only = 0
        for ip in ips:
            reply = replies[ip]
            if reply is None:
                continue
            replied += 1
            sightings.append(Sighting(ip, arp.get(ip), reply.rtt_ms, reply.ttl, now))
        for ip, mac in arp.items():  # the ARP table also lists WSL, Hyper-V and VPN neighbours
            if replies.get(ip) is None and mac and _in_subnet(ip, subnet):
                arp_only += 1
                sightings.append(Sighting(ip, mac, None, None, now))
        self._plugin.record_summary(
            hosts=len(ips),
            replied=replied,
            arp_only=arp_only,
            duration_ms=round((time.monotonic() - started) * 1000),
            last_ms=now,
        )
        return sightings


def _in_subnet(ip: str, subnet: IPv4Network) -> bool:
    try:
        return IPv4Address(ip) in subnet
    except ValueError:
        return False


class LanDiscoveryPlugin(Plugin):
    manifest = PluginManifest(
        name="LAN discovery",
        version="0.1.0",
        description="Finds devices with a ping sweep and the ARP table",
        guid="4eddf684-deb5-41cf-9588-020746307ade",
        display_name="LAN discovery",
        plugin_type=PluginType.SOFTWARE,
        sdk_version=">=2.0,<3",
        capabilities=frozenset({Capability.DISCOVERY, Capability.API, Capability.WEB_UI}),
        permissions=frozenset(
            {Permission.DEVICES_READ, Permission.NETWORK_PROBE, Permission.API, Permission.UI}
        ),
    )
    settings_model = LanDiscoverySettings

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._summary: dict[str, Any] = {
            "hosts": 0,
            "replied": 0,
            "arp_only": 0,
            "duration_ms": 0,
            "last_ms": None,
        }
        self._discovery: _Discovery | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._discovery = _Discovery(self, ctx)

    def record_summary(self, **values: Any) -> None:
        with self._lock:
            self._summary = dict(values)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._summary)

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.DISCOVERY: self._discovery} if self._discovery else {}

    def router(self) -> Any:
        return build_router(self.summary)

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")
