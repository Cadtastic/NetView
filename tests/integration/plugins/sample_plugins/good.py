from collections.abc import Iterable, Mapping
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter
from pydantic import BaseModel

from netview.sdk import (
    Capability,
    JobSpec,
    Permission,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginType,
    Sighting,
    StorageSpec,
)

metadata = sa.MetaData()
sa.Table("items", metadata, sa.Column("id", sa.Integer, primary_key=True))


class GoodSettings(BaseModel):
    level: int = 1


class GoodDiscovery:
    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]:
        return []


class GoodPlugin(Plugin):
    manifest = PluginManifest(
        id="good",
        name="Good",
        version="1.0.0",
        description="A well-behaved sample plugin",
        guid="6d7a1ca2-d5eb-4d9b-b861-7600f0fe7768",
        display_name="Good",
        plugin_type=PluginType.OTHER,
        sdk_version=">=1.0,<2",
        capabilities=frozenset({Capability.DISCOVERY, Capability.JOBS, Capability.API, Capability.STORAGE}),
        permissions=frozenset({Permission.API, Permission.STORAGE_OWN}),
    )
    settings_model = GoodSettings

    def __init__(self) -> None:
        self.changed: list[Any] = []
        self.ctx: Any = None

    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings

    def providers(self) -> Mapping[Capability, object]:
        return {Capability.DISCOVERY: GoodDiscovery()}

    def jobs(self) -> list[JobSpec]:
        return [JobSpec(name="tick", interval_s=60.0, run=lambda: None)]

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/ping")
        def ping() -> dict[str, bool]:
            return {"pong": True}

        return router

    def storage(self) -> StorageSpec:
        return StorageSpec(metadata=metadata, versions_dir=Path(__file__).parent / "good_versions")

    def on_settings_changed(self, settings: Any) -> None:
        super().on_settings_changed(settings)
        self.changed.append(settings)
