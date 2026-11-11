"""Builders for the API tests: AppServices wired from in-memory fakes."""

import logging
from dataclasses import dataclass
from ipaddress import IPv4Network
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netview.application.plugins.plugin_json import CatalogEntry, PluginIndex, PluginJson, build_index
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.ports.plugin_catalog import CatalogSnapshot, Progress
from netview.application.ports.themes import ThemeCatalog, ThemeInfo
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.services import AppServices
from netview.application.usecases.forget import ForgetDevice
from netview.application.usecases.health import WatchMonitor
from netview.application.usecases.inspection import RunInspection
from netview.application.usecases.install_plugin import InstallJobs
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.plugin_catalog import PluginCatalogService
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings
from netview.application.usecases.traffic import TrafficLedger
from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.errors import CatalogUnavailableError, ConflictError, NotFoundError, ValidationError
from netview.domain.samples import Sighting
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.metrics import LONG_MAXLEN, LONG_PREFIXES, RingMetricsStore
from netview.infrastructure.state_notifier import InMemoryStateNotifier
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

    def _refuse_pending(self, info: PluginInfo) -> None:
        if info.state == "pending":
            raise ConflictError(f"{info.name} loads the next time netview starts")

    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo:
        info = self.get(plugin_id)
        self._refuse_pending(info)
        if values.get("interval", 0) < 0:
            raise ValidationError("interval must be positive", fields={"interval": "Must be positive"})
        self.calls.append(("settings", values))
        info.settings = dict(values)
        return info

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        info = self.get(plugin_id)
        self._refuse_pending(info)
        self.calls.append(("enabled", enabled))
        info.enabled = enabled
        info.restart_required = True
        return info


def catalog_plugin(plugin_id: str, **kw: Any) -> PluginJson:
    fields: dict[str, Any] = {
        "id": plugin_id,
        "name": plugin_id.title(),
        "version": "0.1.0",
        "description": f"The {plugin_id} plugin",
        "sdk_version": ">=1.3,<2",
        "capabilities": ("api",),
        "permissions": ("api",),
    }
    fields.update(kw)
    return PluginJson(**fields)


def catalog_index(*ids: str) -> PluginIndex:
    return build_index([catalog_plugin(i) for i in ids], "main", "https://example.test/archive.zip")


class MemCatalogStore:
    def __init__(self) -> None:
        self.snapshot: CatalogSnapshot | None = None

    def load(self) -> CatalogSnapshot | None:
        return self.snapshot

    def save(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot


class StubCatalogFetcher:
    source = "https://example.test/plugins/index.json"

    def __init__(self) -> None:
        self.result: PluginIndex | CatalogUnavailableError = catalog_index("alpha", "beta")

    def fetch(self) -> PluginIndex:
        if isinstance(self.result, CatalogUnavailableError):
            raise self.result
        return self.result


class StubInstaller:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.installed: list[str] = []

    def install(self, entry: CatalogEntry, archive_url: str, progress: Progress) -> None:
        progress("downloading", 50)
        progress("installing", None)
        if self.error:
            raise self.error
        self.installed.append(entry.plugin.id)


class StubThemes:
    def list(self) -> list[ThemeInfo]:
        return []

    def user_dir(self) -> str:
        return ""


@dataclass
class ApiWorld:
    services: AppServices
    uow: InMemoryUnitOfWorkFactory
    bus: InMemoryEventBus
    registry: CapabilityRegistry
    admin: StubPluginAdmin
    clock: FakeClock
    notifier: InMemoryStateNotifier
    metrics: RingMetricsStore
    fetcher: StubCatalogFetcher
    installer: StubInstaller

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


def build_world(themes: ThemeCatalog | None = None) -> ApiWorld:
    uow = InMemoryUnitOfWorkFactory()
    clock = FakeClock()
    bus = InMemoryEventBus()
    notifier = InMemoryStateNotifier()
    registry = CapabilityRegistry()
    metrics = RingMetricsStore(long_prefixes=LONG_PREFIXES, long_maxlen=LONG_MAXLEN)
    scheduler = StubScheduler()
    admin = StubPluginAdmin()
    record = RecordSightings(uow, clock, FakeVendors(), bus, lambda: SELF_IP)
    fetcher = StubCatalogFetcher()
    catalog = PluginCatalogService(
        MemCatalogStore(),
        fetcher,
        lambda: catalog_index("alpha"),
        admin,
        clock,
        "1.3",
        lambda name: True,
    )
    installer = StubInstaller()
    installs = InstallJobs(catalog, installer, admin, lambda work: work(), "1.3", lambda name: True)
    host = HostInfo("test-host", SELF_IP, "192.168.1.1", "192.168.1.0/24", "test")
    services = AppServices(
        state=GetNetworkState(
            uow,
            registry,
            scheduler,
            lambda: host,
            monitor=WatchMonitor(uow, bus, clock),
            ledger=TrafficLedger(metrics),
        ),
        device=GetDevice(uow),
        set_nickname=SetNickname(uow, clock, bus),
        forget_device=ForgetDevice(uow, bus, clock),
        add_watch=AddWatch(uow, bus, clock),
        remove_watch=RemoveWatch(uow, bus, clock),
        run_scan=RunScan(registry, record, lambda: IPv4Network("192.168.1.0/24"), logging.getLogger("t")),
        run_inspection=RunInspection(registry, uow, clock),
        events=lambda limit: _events(uow, limit),
        latest_inspection=lambda ip: _latest(uow, ip),
        plugins=admin,
        bus=bus,
        scheduler=scheduler,
        notifier=notifier,
        themes=themes or StubThemes(),
        metrics=metrics,
        catalog=catalog,
        installs=installs,
    )
    return ApiWorld(services, uow, bus, registry, admin, clock, notifier, metrics, fetcher, installer)


def make_app(world: ApiWorld, routers: list[Any] | None = None, ui: list[Any] | None = None) -> FastAPI:
    return create_app(world.services, routers or [], ui or [], set(ALLOWED))


def make_client(app: FastAPI, with_header: bool = True) -> TestClient:
    """A client whose Host is localhost; ``with_header`` adds X-Netview: 1."""
    return TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"} if with_header else {})
