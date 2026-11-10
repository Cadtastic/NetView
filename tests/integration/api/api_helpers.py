"""Builders for the API tests: AppServices wired from in-memory fakes."""

import logging
from dataclasses import dataclass
from ipaddress import IPv4Network
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.services import AppServices
from netview.application.usecases.inspection import RunInspection
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings
from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.errors import NotFoundError, ValidationError
from netview.domain.samples import Sighting
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.presentation.api.app import create_app
from netview.sdk.testing.fakes import FakeClock, FakeVendors, InMemoryUnitOfWorkFactory

SELF_IP = "192.168.1.95"
ALLOWED = {"localhost", "127.0.0.1", "[::1]"}


class StubScheduler:
    def add(self, owner: str, spec: Any) -> None: ...
    def remove_owner(self, owner: str) -> None: ...
    def run_now(self, owner: str, name: str) -> None: ...
    def status(self) -> list[Any]:
        return []


class StubPluginAdmin:
    def __init__(self) -> None:
        self.plugins = {
            "demo": PluginInfo("demo", "Demo", "1.0.0", "A demo", "active", settings={"interval": 5})
        }
        self.calls: list[tuple[str, Any]] = []

    def list(self) -> list[PluginInfo]:
        return list(self.plugins.values())

    def get(self, plugin_id: str) -> PluginInfo:
        try:
            return self.plugins[plugin_id]
        except KeyError:
            raise NotFoundError(f"unknown plugin {plugin_id!r}") from None

    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo:
        info = self.get(plugin_id)
        if values.get("interval", 0) < 0:
            raise ValidationError("interval must be positive")
        self.calls.append(("settings", values))
        info.settings = dict(values)
        return info

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        info = self.get(plugin_id)
        self.calls.append(("enabled", enabled))
        info.enabled = enabled
        info.restart_required = True
        return info


@dataclass
class ApiWorld:
    services: AppServices
    uow: InMemoryUnitOfWorkFactory
    bus: InMemoryEventBus
    registry: CapabilityRegistry
    admin: StubPluginAdmin
    clock: FakeClock

    def add_device(self, ip: str, mac: str | None = "aa:bb:cc:dd:ee:01") -> str:
        record = RecordSightings(self.uow, self.clock, FakeVendors(), self.bus, lambda: SELF_IP)
        record([Sighting(ip, mac, 1.0, 64, self.clock.now_ms())])
        return mac or f"ip:{ip}"


def _events(uow: InMemoryUnitOfWorkFactory, limit: int) -> list[Any]:
    with uow() as u:
        return u.events.recent(limit)


def _latest(uow: InMemoryUnitOfWorkFactory, ip: str) -> Any:
    with uow() as u:
        return u.inspections.latest(ip)


def build_world() -> ApiWorld:
    uow = InMemoryUnitOfWorkFactory()
    clock = FakeClock()
    bus = InMemoryEventBus()
    registry = CapabilityRegistry()
    scheduler = StubScheduler()
    admin = StubPluginAdmin()
    record = RecordSightings(uow, clock, FakeVendors(), bus, lambda: SELF_IP)
    host = HostInfo("test-host", SELF_IP, "192.168.1.1", "192.168.1.0/24", "test")
    services = AppServices(
        state=GetNetworkState(uow, registry, scheduler, lambda: host),
        device=GetDevice(uow),
        set_nickname=SetNickname(uow, clock, bus),
        add_watch=AddWatch(uow, bus, clock),
        remove_watch=RemoveWatch(uow, bus, clock),
        run_scan=RunScan(registry, record, lambda: IPv4Network("192.168.1.0/24"), logging.getLogger("t")),
        run_inspection=RunInspection(registry, uow, clock),
        events=lambda limit: _events(uow, limit),
        latest_inspection=lambda ip: _latest(uow, ip),
        plugins=admin,
        bus=bus,
        scheduler=scheduler,
    )
    return ApiWorld(services, uow, bus, registry, admin, clock)


def make_app(world: ApiWorld, routers: list[Any] | None = None, ui: list[Any] | None = None) -> FastAPI:
    return create_app(world.services, routers or [], ui or [], set(ALLOWED))


def make_client(app: FastAPI, with_header: bool = True) -> TestClient:
    """A client whose Host is localhost; ``with_header`` adds X-Netview: 1."""
    return TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"} if with_header else {})
