"""NETGEAR GSM7248 switch plugin: ports, VLANs, spanning tree, traffic and device-to-port mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from netview.sdk import (
    Capability,
    JobSpec,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    StorageSpec,
    UiContribution,
)

from .collector import Collector
from .console import SerialConsole, SubprocessRunner
from .routes import build_router
from .service import Gsm7248Service
from .settings import Gsm7248Settings
from .storage import SwitchStore, storage_spec

_MAX_JOB_TIMEOUT_S = 120.0


class Gsm7248Plugin(Plugin):
    manifest = PluginManifest(
        id="gsm7248",
        name="NETGEAR GSM7248",
        version="0.1.0",
        description=(
            "Ports, VLANs, spanning tree, traffic and device-to-port mapping for the GSM7248 switch over SNMP"
        ),
        guid="3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4",
        display_name="GSM7248",
        plugin_type=PluginType.SWITCH,
        sdk_version=">=1.3,<2",
        capabilities=frozenset({Capability.API, Capability.WEB_UI, Capability.STORAGE, Capability.JOBS}),
        permissions=frozenset(
            {
                Permission.DEVICES_READ,
                Permission.NAMES_WRITE,
                Permission.TYPES_WRITE,
                Permission.STORAGE_OWN,
                Permission.API,
                Permission.UI,
                Permission.NETWORK_PROBE,
            }
        ),
    )
    settings_model = Gsm7248Settings

    def __init__(self) -> None:
        self._service: Gsm7248Service | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._service = Gsm7248Service(
            ctx,
            lambda switch_id: SwitchStore(ctx.unit_of_work, switch_id),
            Collector(ctx.snmp),
            SerialConsole(SubprocessRunner()),
        )

    def on_settings_changed(self, settings: Any) -> None:
        self.settings = settings
        if self._service is not None:
            self._service.settings_changed()

    def storage(self) -> StorageSpec:
        return storage_spec()

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")

    def router(self) -> APIRouter:
        # the host asks for the router once before setup (to validate capabilities) and once after
        return build_router(self._service) if self._service is not None else APIRouter()

    def jobs(self) -> list[JobSpec]:
        service = self._service
        settings: Gsm7248Settings | None = self.settings
        prune = JobSpec("prune", 3600, service.prune if service else _noop, timeout_s=_MAX_JOB_TIMEOUT_S)
        if service is None or settings is None or settings.target() is None:
            return [prune]

        def job(name: str, interval_s: int, run: Any, delay_s: float) -> JobSpec:
            return JobSpec(
                name,
                interval_s,
                run,
                timeout_s=min(2.0 * interval_s, _MAX_JOB_TIMEOUT_S),
                initial_delay_s=delay_s,
            )

        return [
            job("counters", settings.counters_interval_s, service.poll_counters, 2),
            job("status", settings.status_interval_s, service.poll_status, 5),
            job("bridge", settings.bridge_interval_s, service.poll_bridge, 8),
            job("topology", settings.topology_interval_s, service.poll_topology, 11),
            prune,
        ]


def _noop() -> None:
    return None
