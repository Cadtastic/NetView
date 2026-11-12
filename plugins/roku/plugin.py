"""Roku plugin: finds Roku TVs on the network and controls them over ECP."""

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

from .ecp import EcpClient, urllib_transport
from .routes import build_router
from .service import RokuService
from .settings import RokuSettings
from .storage import TvStore, storage_spec

_STATUS_DELAY_S = 3
_SCAN_DELAY_S = 5
_SCAN_TIMEOUT_S = 120.0
_STARTUP_ONLY_INTERVAL_S = 10**9
_MAX_STATUS_TIMEOUT_S = 60.0


class RokuPlugin(Plugin):
    manifest = PluginManifest(
        name="Roku",
        version="0.1.0",
        description="Finds Roku TVs on the network, shows what they are playing and works as their remote",
        guid="241d4d28-4a70-406c-833c-a7b4d5b389a9",
        display_name="Roku",
        plugin_type=PluginType.TV,
        sdk_version=">=2.0,<3",
        capabilities=frozenset({Capability.STORAGE, Capability.API, Capability.WEB_UI, Capability.JOBS}),
        permissions=frozenset(
            {
                Permission.STORAGE_OWN,
                Permission.API,
                Permission.UI,
                Permission.NETWORK_PROBE,
                Permission.NETWORK_CONTROL,
            }
        ),
    )
    settings_model = RokuSettings

    def __init__(self) -> None:
        self._service: RokuService | None = None
        self._startup_scan_ran = False

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        settings = ctx.settings if isinstance(ctx.settings, RokuSettings) else RokuSettings()
        # urllib_transport is looked up here, at setup time, so tests can monkeypatch this module's name
        ecp = EcpClient(urllib_transport, settings.request_timeout_s)
        self._service = RokuService(ctx, TvStore(ctx.unit_of_work), ecp)

    def on_settings_changed(self, settings: Any) -> None:
        self.settings = settings
        if self._service is not None and isinstance(settings, RokuSettings):
            self._service.settings_changed(settings)

    def storage(self) -> StorageSpec:
        return storage_spec()

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")

    def router(self) -> APIRouter:
        # the host asks for the router once before setup (to validate capabilities) and once after
        return build_router(self._service) if self._service is not None else APIRouter()

    def _run_scan(self) -> None:
        """The scan job. The host re-adds jobs on every settings save, so remember that this one has run."""
        self._startup_scan_ran = True
        if self._service is not None:
            self._service.run_scan()

    def jobs(self) -> list[JobSpec]:
        service = self._service
        settings = self.settings
        if service is None or not isinstance(settings, RokuSettings):
            return []
        jobs = [
            JobSpec(
                "status",
                settings.status_interval_s,
                service.poll_status,
                timeout_s=min(2.0 * settings.status_interval_s, _MAX_STATUS_TIMEOUT_S),
                initial_delay_s=_STATUS_DELAY_S,
            )
        ]
        if settings.auto_scan == "startup_and_every":
            interval_s = settings.scan_every_h * 3600
            delay_s = interval_s if self._startup_scan_ran else _SCAN_DELAY_S
            jobs.append(
                JobSpec(
                    "scan", interval_s, self._run_scan, timeout_s=_SCAN_TIMEOUT_S, initial_delay_s=delay_s
                )
            )
        elif settings.auto_scan == "startup" and not self._startup_scan_ran:
            jobs.append(
                JobSpec(
                    "scan",
                    _STARTUP_ONLY_INTERVAL_S,
                    self._run_scan,
                    timeout_s=_SCAN_TIMEOUT_S,
                    initial_delay_s=_SCAN_DELAY_S,
                )
            )
        return jobs
