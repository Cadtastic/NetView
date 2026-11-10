"""Composition root: builds every adapter, use case and the plugin host, and the FastAPI app."""

from __future__ import annotations

import ipaddress
import logging
import sys
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from netview.application.plugins.core_facade import CoreFacade
from netview.application.plugins.jobs import JobSpec
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.uow import UnitOfWork
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.services import AppServices
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.inspection import RunInspection
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings
from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.errors import CapabilityUnavailableError, ValidationError
from netview.domain.events import DomainEvent
from netview.domain.inspection import InspectionReport
from netview.infrastructure.clock import SystemClock
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.lanmon_import import LanmonImporter
from netview.infrastructure.metrics import RingMetricsStore
from netview.infrastructure.net.tools import SystemNetworkTools
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.infrastructure.plugins.discovery import discover_plugin_classes
from netview.infrastructure.plugins.host import PluginHost
from netview.infrastructure.scheduler import AsyncScheduler
from netview.infrastructure.settings import AppSettings, load_settings
from netview.infrastructure.vendor import OuiVendorLookup
from netview.presentation.api.app import create_app

log = logging.getLogger(__name__)

MAX_HOSTS = 1024  # the same limit as the old LAN monitor
_GATEWAY_TTL_S = 30.0
_SCAN_TIMEOUT_S = 120.0


@dataclass
class Container:
    settings: AppSettings
    engine: Engine
    subnet: IPv4Network
    registry: CapabilityRegistry
    scheduler: AsyncScheduler
    host: PluginHost
    core: CoreFacade
    services: AppServices
    importer: LanmonImporter


def make_settings(config_file: Path | None = None, **overrides: Any) -> AppSettings:
    """Settings for the CLI: init args > environment > TOML file (``data_dir/netview.toml`` by default)."""
    return load_settings(config_file, **overrides)


def resolve_subnet(spec: str | None, local_ip: str) -> IPv4Network:
    """``spec`` or ``<local_ip>/24``; networks above MAX_HOSTS hosts are rejected."""
    text = spec or f"{local_ip}/24"
    try:
        network = ipaddress.IPv4Network(text, strict=False)
    except ValueError as exc:
        raise ValidationError(f"invalid subnet {text!r}: {exc}") from exc
    if network.num_addresses > MAX_HOSTS + 2:
        raise ValidationError(f"{network} has more than {MAX_HOSTS} hosts; configure a smaller subnet")
    return network


def build_container(settings: AppSettings) -> Container:
    engine = make_engine(settings.db_url)
    upgrade_core(engine)
    sessions = sessionmaker(engine)

    def uow() -> UnitOfWork:
        # the Protocol declares plain attributes, which are invariant; SqlUnitOfWork narrows them
        return cast(UnitOfWork, SqlUnitOfWork(sessions))

    clock = SystemClock()
    bus = InMemoryEventBus()
    metrics = RingMetricsStore()
    net = SystemNetworkTools()
    vendors = OuiVendorLookup(settings.oui_file)
    registry = CapabilityRegistry()
    scheduler = AsyncScheduler(clock)

    local_ip = net.local_ip()
    subnet = resolve_subnet(settings.subnet, local_ip)
    gateway_cache: tuple[float, str | None] | None = None

    def host_info() -> HostInfo:
        nonlocal gateway_cache
        now = time.monotonic()
        if gateway_cache is None or now - gateway_cache[0] > _GATEWAY_TTL_S:
            gateway_cache = (now, net.default_gateway(local_ip))
        return HostInfo(net.hostname(), local_ip, gateway_cache[1], str(subnet), sys.platform)

    record = RecordSightings(uow, clock, vendors, bus, net.local_ip)
    claim = ClaimIdentity(uow, bus)
    scan = RunScan(registry, record, lambda: subnet, logging.getLogger("netview.scan"))
    state = GetNetworkState(uow, registry, scheduler, host_info)
    device = GetDevice(uow)
    core = CoreFacade(state, device, uow, record, claim, scan, bus, clock)

    def context_factory(plugin_id: str, plugin_settings: Any) -> DefaultPluginContext:
        return DefaultPluginContext(
            plugin_id, plugin_settings, engine, clock, net, vendors, metrics, core, bus
        )

    host = PluginHost(
        engine=engine,
        uow=uow,
        registry=registry,
        scheduler=scheduler,
        context_factory=context_factory,
        seeds=settings.plugins,
        discovered=discover_plugin_classes(extra_dirs=settings.plugin_dirs),
    )
    host.load_all()

    def recent_events(limit: int) -> list[DomainEvent]:
        with uow() as u:
            return u.events.recent(limit)

    def latest_inspection(ip: str) -> InspectionReport | None:
        with uow() as u:
            return u.inspections.latest(ip)

    services = AppServices(
        state=state,
        device=device,
        set_nickname=SetNickname(uow, clock, bus),
        add_watch=AddWatch(uow, bus, clock),
        remove_watch=RemoveWatch(uow, bus, clock),
        run_scan=scan,
        run_inspection=RunInspection(registry, uow, clock),
        events=recent_events,
        latest_inspection=latest_inspection,
        plugins=host,
        bus=bus,
        scheduler=scheduler,
    )
    importer = LanmonImporter(uow, clock)
    return Container(settings, engine, subnet, registry, scheduler, host, core, services, importer)


def _scan_job(container: Container) -> Callable[[], None]:
    warned = False

    def run() -> None:
        nonlocal warned
        try:
            container.services.run_scan()
        except CapabilityUnavailableError as exc:
            if not warned:  # no discovery plugin is enabled: say so once, not every interval
                log.warning("scheduled scan skipped: %s", exc)
                warned = True
        else:
            warned = False

    return run


def create_application(settings: AppSettings) -> FastAPI:
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await container.scheduler.start()
        container.scheduler.add(
            "core",
            JobSpec("scan", settings.scan_interval_s, _scan_job(container), timeout_s=_SCAN_TIMEOUT_S),
        )
        container.host.start_jobs()
        try:
            yield
        finally:
            await container.scheduler.stop()
            container.host.shutdown()
            container.engine.dispose()

    allowed = {"localhost", "127.0.0.1", "[::1]", settings.bind}
    return create_app(
        container.services,
        container.host.routers(),
        container.host.ui_contributions(),
        allowed,
        lifespan=lifespan,
    )
