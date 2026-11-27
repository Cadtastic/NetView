"""GeoTrace plugin: traces routes to saved targets and draws the hops on a globe."""

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

from .service import GeoTraceService
from .settings import GeoTraceSettings
from .storage import storage_spec


class GeoTracePlugin(Plugin):
    manifest = PluginManifest(
        name="GeoTrace",
        version="0.1.0",
        description="Traces the route to saved targets on a schedule and draws the hops on a globe",
        guid="f64f43b1-9ff2-47b9-badf-390b2fef25db",
        display_name="GeoTrace",
        plugin_type=PluginType.SOFTWARE,
        sdk_version=">=2.1,<3",
        capabilities=frozenset({Capability.STORAGE, Capability.API, Capability.WEB_UI, Capability.JOBS}),
        permissions=frozenset(
            {
                Permission.STORAGE_OWN,
                Permission.API,
                Permission.UI,
                Permission.NETWORK_PROBE,
                Permission.NETWORK_INTERNET,
            }
        ),
    )
    settings_model = GeoTraceSettings

    def __init__(self) -> None:
        self._service: GeoTraceService | None = None

    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        settings = ctx.settings if isinstance(ctx.settings, GeoTraceSettings) else GeoTraceSettings()
        self._service = GeoTraceService(ctx, settings)
        self._service.start()

    def on_settings_changed(self, settings: Any) -> None:
        self.settings = settings
        if self._service is not None and isinstance(settings, GeoTraceSettings):
            self._service.settings_changed(settings)

    def shutdown(self) -> None:
        if self._service is not None:
            self._service.stop()

    def storage(self) -> StorageSpec:
        return storage_spec()

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")

    def router(self) -> APIRouter:
        return APIRouter()

    def jobs(self) -> list[JobSpec]:
        service = self._service
        if service is None:
            return []
        jobs = [
            JobSpec("tick", 30, service.tick, timeout_s=10, initial_delay_s=15),
            JobSpec("cleanup", 86400, service.cleanup, timeout_s=120, initial_delay_s=600),
        ]
        settings = self.settings
        if isinstance(settings, GeoTraceSettings) and settings.geo_auto_update:
            jobs.append(JobSpec("geodata", 86400, service.update_geo, timeout_s=600, initial_delay_s=60))
        return jobs
