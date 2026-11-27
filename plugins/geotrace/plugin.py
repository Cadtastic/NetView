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

    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings

    def on_settings_changed(self, settings: Any) -> None:
        self.settings = settings

    def storage(self) -> StorageSpec:
        return storage_spec()

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")

    def router(self) -> APIRouter:
        return APIRouter()

    def jobs(self) -> list[JobSpec]:
        return []
