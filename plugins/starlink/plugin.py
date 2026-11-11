"""Per-device traffic, signal and names from a Starlink router's local API (read-only).

The core polls ``read()`` (the ``poll.traffic`` job), so a router that is not there, is not a Starlink or
sends garbage makes that job fail and the scheduler back off; nothing else is affected.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from netview.sdk import (
    NAME_RANKS,
    Capability,
    NameClaim,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    StorageSpec,
    TrafficReading,
    UiContribution,
)

from . import storage
from .client import Post, _http_post, starlink_clients
from .routes import build_router
from .settings import StarlinkSettings

BASELINE_MAX_AGE_MS = 60_000  # a stored reading younger than this seeds the first rate after a restart


class StarlinkPlugin(Plugin):
    manifest = PluginManifest(
        id="starlink",
        name="Starlink router",
        version="0.1.0",
        description="Per-device traffic, signal and names from a Starlink router's local API (read-only)",
        sdk_version=">=1.1,<2",
        capabilities=frozenset({Capability.TRAFFIC, Capability.STORAGE, Capability.API, Capability.WEB_UI}),
        permissions=frozenset(
            {
                Permission.DEVICES_READ,
                Permission.NAMES_WRITE,
                Permission.TRAFFIC_WRITE,
                Permission.STORAGE_OWN,
                Permission.NETWORK_PROBE,
                Permission.API,
                Permission.UI,
            }
        ),
    )
    settings_model = StarlinkSettings

    def __init__(self) -> None:
        self.post: Post = _http_post  # the transport; tests replace it
        self._ctx: PluginContext | None = None
        self._lock = threading.Lock()
        self._primed = False  # True once a read has succeeded since setup
        self._target: str | None = None
        self._last_ok_ms: int | None = None
        self._error = ""

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._ctx = ctx
        self._primed = False

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.TRAFFIC: self}

    def storage(self) -> StorageSpec:
        return StorageSpec(metadata=storage.metadata, versions_dir=Path(__file__).parent / "versions")

    # ---- TrafficProvider

    def read(self) -> Iterable[TrafficReading]:
        ctx = self._require()
        settings: StarlinkSettings = self.settings
        target = settings.router or self._gateway()
        with self._lock:
            self._target = target
        if target is None:
            with self._lock:
                self._error = "no router address and no gateway"
            raise OSError("no router address and no gateway")
        try:
            clients = starlink_clients(target, settings.port, settings.timeout_s, post=self.post)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
            raise
        now = ctx.clock.now_ms()
        with self._lock:
            self._last_ok_ms = now
            self._error = ""
            first = not self._primed
            self._primed = True

        readings: list[TrafficReading] = []
        for c in clients:
            extra = {
                "name": c["name"],
                "signal_dbm": c["signal"],
                "down_link": c["down_link"],
                "up_link": c["up_link"],
                "assoc_s": c["assoc_s"],
                "role": c["role"],
                "ap": c["ap"],
            }
            readings.append(TrafficReading(c["ip"], now, c["down_bytes"], c["up_bytes"], extra))

        baselines = self._remember(readings, clients, now, first)
        self._claim_names(clients, now)
        return baselines + readings

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"target": self._target, "last_ok_ms": self._last_ok_ms, "error": self._error}

    # ---- the pieces

    def _gateway(self) -> str | None:
        ctx = self._require()
        try:
            return ctx.core.host().gateway or None
        except Exception:
            ctx.log.debug("could not read the gateway", exc_info=True)
            return None

    def _remember(
        self, readings: list[TrafficReading], clients: list[dict[str, Any]], now: int, first: bool
    ) -> list[TrafficReading]:
        """Store the new counters. On the first read after setup, also return the readings to start from.

        A client listed without byte counters has nothing to store and no baseline.
        """
        ctx = self._require()
        baselines: list[TrafficReading] = []
        counted = [
            (r, r.down_bytes, r.up_bytes)
            for r in readings
            if r.down_bytes is not None and r.up_bytes is not None
        ]
        names = {c["ip"]: c["name"] for c in clients}
        try:
            with ctx.unit_of_work() as uow:
                if first:
                    old = storage.load(uow.session)
                    for r, down, up in counted:
                        row = old.get(r.ip)
                        if (
                            row is not None
                            and 0 <= r.t_ms - row.t_ms < BASELINE_MAX_AGE_MS
                            and row.down_bytes <= down
                            and row.up_bytes <= up
                        ):
                            baselines.append(
                                TrafficReading(r.ip, row.t_ms, row.down_bytes, row.up_bytes, r.extra)
                            )
                rows = [
                    storage.StoredCounter(r.ip, str(names.get(r.ip, ""))[:60], down, up, r.t_ms)
                    for r, down, up in counted
                ]
                storage.save(uow.session, rows, now)
                uow.commit()
        except Exception:
            ctx.log.warning("could not store the router's counters", exc_info=True)
        return baselines

    def _claim_names(self, clients: list[dict[str, Any]], now: int) -> None:
        """A client's DHCP name for the device at its address (LM 1457-1459); never for this device."""
        ctx = self._require()
        claims: list[NameClaim] = []
        for c in clients:
            if not c["name"]:
                continue
            try:
                device = ctx.core.device_by_ip(c["ip"])
            except Exception:
                ctx.log.debug("could not look up %s", c["ip"], exc_info=True)
                continue
            if device is None or getattr(device, "is_self", False):
                continue
            claims.append(NameClaim(device.key, c["name"], "DHCP", NAME_RANKS["DHCP"], now))
        if claims:
            try:
                ctx.core.claim(claims)
            except Exception:
                ctx.log.warning("could not store the names the router reported", exc_info=True)

    def _require(self) -> PluginContext:
        if self._ctx is None:
            raise RuntimeError("starlink used before setup")
        return self._ctx

    def router(self) -> Any:
        return build_router(self.status)

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")
