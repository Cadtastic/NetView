"""NETGEAR GS105E switch plugin: ports, VLANs, QoS and traffic read from the switch's web pages."""

from __future__ import annotations

from collections.abc import Callable
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

from . import client as _client
from .routes import build_router
from .service import Gs105eService
from .settings import Gs105eSettings
from .storage import SwitchStore, storage_spec

_MAX_JOB_TIMEOUT_S = 120.0


class Gs105ePlugin(Plugin):
    manifest = PluginManifest(
        id="gs105e",
        name="NETGEAR GS105E",
        version="0.1.0",
        description="Ports, VLANs, QoS and traffic for the GS105Ev2 switch, read from its web pages",
        guid="c66a564b-0254-44cf-bb74-1c7f6ebae6be",
        display_name="GS105E",
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
    settings_model = Gs105eSettings

    def __init__(self) -> None:
        # the service is built by setup(); the transport is read here so tests can patch it first
        self._service: Gs105eService | None = None
        self.fetch = _client.http_fetch

    def setup(self, ctx: PluginContext) -> None:
        self.settings = ctx.settings
        self._service = Gs105eService(
            ctx, lambda switch_id: SwitchStore(ctx.unit_of_work, switch_id), self.fetch
        )

    def on_settings_changed(self, settings: Any) -> None:
        self.settings = settings
        if self._service is not None:
            self._service.settings_changed()

    def shutdown(self) -> None:
        if self._service is not None:
            self._service.shutdown()

    def storage(self) -> StorageSpec:
        return storage_spec()

    def ui(self) -> UiContribution:
        return UiContribution(static_dir=Path(__file__).parent / "static", module="ui.js")

    def router(self) -> APIRouter:
        # the host asks for the router once before setup (to validate capabilities) and once after
        return build_router(self._service) if self._service is not None else APIRouter()

    def jobs(self) -> list[JobSpec]:
        service = self._service
        # every 5 minutes: each closed 5-minute bucket is rolled up at once; the 24 h and 7 d charts read them
        prune = JobSpec("prune", 300, service.prune if service else _noop, timeout_s=_MAX_JOB_TIMEOUT_S)
        settings = self.settings
        if service is None or settings is None or not settings.configured():
            return [prune]  # nothing touches the network until a password is set
        return [
            _poll_job("counters", settings.counters_interval_s, service.poll_counters, 2),
            _poll_job("status", settings.status_interval_s, service.poll_status, 5),
            _poll_job("config", settings.config_interval_s, service.poll_config, 8),
            prune,
        ]


def _poll_job(name: str, interval_s: int, run: Callable[[], None], delay_s: float) -> JobSpec:
    timeout_s = min(2 * interval_s, _MAX_JOB_TIMEOUT_S)
    return JobSpec(name, interval_s, run, timeout_s=timeout_s, initial_delay_s=delay_s)


def _noop() -> None:
    return None
