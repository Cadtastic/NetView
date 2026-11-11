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
        id="roku",
        name="Roku",
        version="0.1.0",
        description="Finds Roku TVs on the network, shows what they are playing and works as their remote",
        sdk_version=">=1.4,<2",
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
        if settings.auto_scan != "never":
            interval_s = (
                _STARTUP_ONLY_INTERVAL_S if settings.auto_scan == "startup" else settings.scan_every_h * 3600
            )
            jobs.append(
                JobSpec(
                    "scan",
                    interval_s,
                    service.run_scan,
                    timeout_s=_SCAN_TIMEOUT_S,
                    initial_delay_s=_SCAN_DELAY_S,
                )
            )
        return jobs
