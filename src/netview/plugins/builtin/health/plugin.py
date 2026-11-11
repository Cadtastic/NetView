"""Latency, DNS timing and watch checks (ported from the old LAN monitor's fast tick and check_watch)."""

from __future__ import annotations

import random
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path
from typing import Any, Literal

from netview.plugins.builtin.health.routes import build_router
from netview.plugins.builtin.health.settings import HealthSettings
from netview.sdk import (
    Capability,
    HealthTargets,
    LatencySample,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    UiContribution,
    Watch,
    WatchProbe,
)

_FALLBACK_DNS = "1.1.1.1"
_WATCH_PING_MS = 1000  # LM 1337
_MAX_DNS_SERVERS = 2

PortState = Literal["open", "closed", "filtered"]


def _in_subnet(ip: str, targets: HealthTargets) -> bool:
    try:
        return IPv4Address(ip) in targets.subnet
    except (AddressValueError, ValueError):
        return False


def dns_servers_for(settings: HealthSettings, gateway: str | None) -> list[str]:
    """The servers to time: the configured ones, else the gateway and 1.1.1.1 (no duplicates, at most two)."""
    if settings.dns_servers:
        chosen = list(settings.dns_servers)
    else:
        chosen = [s for s in (gateway, _FALLBACK_DNS) if s]
    return list(dict.fromkeys(chosen))[:_MAX_DNS_SERVERS]


class _Health:
    def __init__(self, plugin: HealthPlugin, ctx: PluginContext) -> None:
        self._plugin = plugin
        self._ctx = ctx

    def probe(self, targets: HealthTargets) -> list[LatencySample | WatchProbe]:
        try:
            return self._probe(targets)
        except Exception:  # a failed round must not stop the job
            self._ctx.log.warning("health probe failed", exc_info=True)
            return []

    def _probe(self, targets: HealthTargets) -> list[LatencySample | WatchProbe]:
        ctx = self._ctx
        settings: HealthSettings = self._plugin.settings
        started_ms = ctx.clock.now_ms()
        devices = targets.devices[: settings.max_devices]
        servers = dns_servers_for(settings, targets.gateway)
        name = random.choice(settings.dns_names)

        def ping(ip: str, timeout_ms: int) -> float | None:
            try:
                reply = ctx.net.ping(ip, timeout_ms)
            except Exception:
                ctx.log.debug("ping %s failed", ip, exc_info=True)
                return None
            return reply.rtt_ms if reply is not None else None

        def dns(server: str) -> float | None:
            try:
                return ctx.net.dns_query(server, name)
            except Exception:
                ctx.log.debug("dns query to %s failed", server, exc_info=True)
                return None

        def watch(w: Watch) -> WatchProbe | None:
            try:
                return self._check_watch(w, targets, started_ms, settings)
            except Exception:
                ctx.log.debug("watch check %s failed", w.ip, exc_info=True)
                return None

        with ThreadPoolExecutor(max_workers=8 + len(devices) + len(targets.watches)) as pool:
            f_gateway = (
                pool.submit(ping, targets.gateway, settings.ping_timeout_ms) if targets.gateway else None
            )
            f_internet = pool.submit(ping, settings.internet_target, settings.internet_timeout_ms)
            f_dns = [(s, pool.submit(dns, s)) for s in servers]
            f_watch: list[Future[WatchProbe | None]] = [pool.submit(watch, w) for w in targets.watches]
            f_dev = [(key, pool.submit(ping, ip, settings.ping_timeout_ms)) for key, ip in devices]
            gateway = f_gateway.result() if f_gateway else None
            internet = f_internet.result()
            dns_times = [(s, f.result()) for s, f in f_dns]
            watch_probes = [p for p in (f.result() for f in f_watch) if p is not None]
            device_times = [(key, f.result()) for key, f in f_dev]

        t_ms = ctx.clock.now_ms()  # one time for every sample of the round
        out: list[LatencySample | WatchProbe] = [
            LatencySample("health.gateway", t_ms, gateway),
            LatencySample("health.internet", t_ms, internet),
        ]
        out += [LatencySample(f"health.dns.{s}", t_ms, v) for s, v in dns_times]
        out += [LatencySample(f"health.device.{key}", t_ms, v) for key, v in device_times]
        out += watch_probes
        return out

    def _check_watch(
        self, w: Watch, targets: HealthTargets, checked_ms: int, settings: HealthSettings
    ) -> WatchProbe:
        """``checked_ms`` is when the round started, so a result that finishes after the watch was
        removed and re-added is still recognised as older than the re-add."""
        ctx = self._ctx
        on_subnet = _in_subnet(w.ip, targets)
        rtt: float | None = None
        try:
            reply = ctx.net.ping(w.ip, _WATCH_PING_MS)
            rtt = reply.rtt_ms if reply is not None else None
        except Exception:
            ctx.log.debug("watch ping %s failed", w.ip, exc_info=True)
        ports: dict[int, PortState] = {}
        if w.ports:
            with ThreadPoolExecutor(max_workers=len(w.ports)) as pool:
                states = list(pool.map(lambda p: self._tcp(w.ip, p, settings.port_timeout_s), w.ports))
            ports = dict(zip(w.ports, states, strict=True))
        mac: str | None = None
        if on_subnet:
            try:
                mac = ctx.net.arp_table().get(w.ip)
            except Exception:
                ctx.log.debug("could not read the ARP table", exc_info=True)
        return WatchProbe(w.ip, checked_ms, on_subnet, bool(mac) if on_subnet else None, mac, rtt, ports)

    def _tcp(self, ip: str, port: int, timeout_s: float) -> PortState:
        try:
            return self._ctx.net.tcp_probe(ip, port, timeout_s).state
        except Exception:
            self._ctx.log.debug("tcp probe %s:%s failed", ip, port, exc_info=True)
            return "filtered"


class HealthPlugin(Plugin):
    manifest = PluginManifest(
        id="health",
        name="Health",
        version="0.1.0",
        description=(
            "Pings the gateway, the internet and every online device, times DNS and checks watched hosts"
        ),
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.HEALTH, Capability.API, Capability.WEB_UI}),
        permissions=frozenset(
            {Permission.DEVICES_READ, Permission.NETWORK_PROBE, Permission.API, Permission.UI}
        ),
    )
    settings_model = HealthSettings

    def __init__(self) -> None:
        self._health: _Health | None = None
        self._ctx: PluginContext | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._ctx = ctx
        self._health = _Health(self, ctx)

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.HEALTH: self._health} if self._health else {}

    def summary(self) -> dict[str, Any]:
        gateway: str | None = None
        if self._ctx is not None:
            try:
                gateway = self._ctx.core.host().gateway
            except Exception:
                self._ctx.log.debug("could not read the gateway", exc_info=True)
        settings: HealthSettings = self.settings
        return {
            "gateway": gateway,
            "internet": settings.internet_target,
            "dns": dns_servers_for(settings, gateway),
        }

    def router(self) -> Any:
        return build_router(self.summary)

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")
