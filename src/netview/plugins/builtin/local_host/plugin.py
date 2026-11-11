"""This device's throughput, Wi-Fi link and TCP connections (ported from the old LAN monitor's slow tick)."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import asdict
from ipaddress import AddressValueError, IPv4Network
from pathlib import Path
from typing import Any

from netview.plugins.builtin.local_host.connections import summarize
from netview.plugins.builtin.local_host.routes import build_router
from netview.plugins.builtin.local_host.settings import LocalHostSettings
from netview.sdk import (
    Capability,
    JobSpec,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    TcpSocket,
    UiContribution,
    WifiInfo,
    counter_rate,
)

_NO_NETWORK = IPv4Network("0.0.0.0/32")  # contains no real address, so every remote reads as outside it


class LocalHostPlugin(Plugin):
    manifest = PluginManifest(
        id="local_host",
        name="This device",
        version="0.1.0",
        description="This device's throughput, Wi-Fi link and TCP connections",
        sdk_version=">=1.1,<2",
        capabilities=frozenset(
            {Capability.LOCAL_HOST, Capability.API, Capability.WEB_UI, Capability.JOBS}
        ),
        permissions=frozenset({Permission.DEVICES_READ, Permission.API, Permission.UI}),
    )
    settings_model = LocalHostSettings

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None
        self._lock = threading.Lock()
        self._last: tuple[int, int, int] | None = None  # down bytes, up bytes, t_ms
        self._snapshot: dict[str, Any] | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._ctx = ctx

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.LOCAL_HOST: self}

    def jobs(self) -> list[JobSpec]:
        # validation asks for the jobs before the settings are loaded, so fall back to the defaults
        settings: LocalHostSettings = self.settings or LocalHostSettings()
        return [
            JobSpec("throughput", settings.throughput_interval_s, self.measure_throughput, timeout_s=15),
            JobSpec("snapshot", settings.connections_interval_s, self.refresh_snapshot, timeout_s=30),
        ]

    # ---- throughput (LM 1401-1409)

    def measure_throughput(self) -> None:
        ctx = self._require()
        try:
            reading = ctx.system.interface_bytes()
        except Exception:
            ctx.log.debug("could not read the interface counters", exc_info=True)
            reading = None
        now = ctx.clock.now_ms()
        down: float | None = None
        up: float | None = None
        with self._lock:
            if reading is not None:
                rate = counter_rate(self._last, reading[0], reading[1], now)
                if rate is not None:
                    down, up = rate
                self._last = (reading[0], reading[1], now)  # a reset becomes the new baseline
        ctx.metrics.append("local.down_bps", now, down)
        ctx.metrics.append("local.up_bps", now, up)

    # ---- Wi-Fi and connections (LM 1488-1529)

    def refresh_snapshot(self) -> dict[str, Any]:
        ctx = self._require()
        wifi: WifiInfo | None = None
        sockets: list[TcpSocket] = []
        try:
            wifi = ctx.system.wifi()
        except Exception:
            ctx.log.debug("could not read the Wi-Fi link", exc_info=True)
        try:
            sockets = ctx.system.tcp_sockets()
        except Exception:
            ctx.log.debug("could not read the TCP sockets", exc_info=True)
        snapshot = {
            "wifi": asdict(wifi) if wifi is not None else None,
            "connections": summarize(sockets, self._subnet(), self._name_for),
            "t_ms": ctx.clock.now_ms(),
        }
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        """The last snapshot, taking one first when there is none yet."""
        with self._lock:
            cached = self._snapshot
        return dict(cached) if cached is not None else dict(self.refresh_snapshot())

    def _subnet(self) -> IPv4Network:
        ctx = self._require()
        try:
            return IPv4Network(ctx.core.host().subnet, strict=False)
        except (AddressValueError, ValueError):
            ctx.log.debug("no usable subnet", exc_info=True)
            return _NO_NETWORK

    def _name_for(self, ip: str) -> str:
        """A device's name, else the label of a watch on that address, else nothing."""
        ctx = self._require()
        try:
            device = ctx.core.device_by_ip(ip)
            if device is not None and device.display_name:
                return str(device.display_name)
            for watch in ctx.core.watches():
                if watch.ip == ip and watch.label:
                    return str(watch.label)
        except Exception:
            ctx.log.debug("could not name %s", ip, exc_info=True)
        return ""

    def _require(self) -> PluginContext:
        if self._ctx is None:
            raise RuntimeError("local_host used before setup")
        return self._ctx

    def router(self) -> Any:
        return build_router(self.snapshot)

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")
