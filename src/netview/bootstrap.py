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

from netview.application.capabilities import (
    Capability,
    HealthProvider,
    IdentityProvider,
    TrafficProvider,
)
from netview.application.plugins.core_facade import CoreFacade
from netview.application.plugins.jobs import JobSpec
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.uow import UnitOfWork
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.services import AppServices
from netview.application.usecases.forget import ForgetDevice
from netview.application.usecases.health import HealthTargetsQuery, PollHealth, WatchMonitor
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.identity_poll import PollIdentity
from netview.application.usecases.inspection import RunInspection
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings
from netview.application.usecases.traffic import PollTraffic, TrafficLedger
from netview.application.usecases.watches import AddWatch, RemoveWatch
from netview.domain.errors import (
    CapabilityUnavailableError,
    NoNetworkError,
    ScanInProgressError,
    ValidationError,
)
from netview.domain.events import DomainEvent
from netview.domain.inspection import InspectionReport
from netview.domain.keys import SELF_KEY
from netview.domain.naming import NAME_RANKS, NameClaim
from netview.infrastructure.clock import SystemClock
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.infrastructure.event_bus import InMemoryEventBus
from netview.infrastructure.lanmon_import import LanmonImporter
from netview.infrastructure.metrics import LONG_MAXLEN, LONG_PREFIXES, RingMetricsStore
from netview.infrastructure.net.probes import SystemServiceProbes
from netview.infrastructure.net.snmp import PysnmpClient
from netview.infrastructure.net.system_info import SystemSystemInfo
from netview.infrastructure.net.tools import SystemNetworkTools
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.infrastructure.plugins.discovery import discover_plugin_classes
from netview.infrastructure.plugins.host import PluginHost
from netview.infrastructure.scheduler import AsyncScheduler
from netview.infrastructure.settings import AppSettings, load_settings
from netview.infrastructure.state_notifier import InMemoryStateNotifier
from netview.infrastructure.themes import FolderThemeCatalog
from netview.infrastructure.vendor import OuiVendorLookup
from netview.presentation.api.app import WEB_STATIC, create_app

log = logging.getLogger(__name__)

MAX_HOSTS = 1024  # the same limit as the old LAN monitor
_HOST_TTL_S = 30.0
_SCAN_TIMEOUT_S = 120.0
_IDENTITY_INTERVAL_S = 60.0  # LM 1650


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
    snmp: PysnmpClient


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


def plugin_folders(settings: AppSettings) -> list[Path]:
    """Where folder plugins are looked for: ``<data dir>/plugins`` (made if missing), then ``plugin_dirs``.

    A plugin is installed by copying its folder into the first one.
    """
    installed = settings.data_dir / "plugins"
    installed.mkdir(parents=True, exist_ok=True)
    return [installed, *(d for d in settings.plugin_dirs if d.resolve() != installed.resolve())]


def build_container(settings: AppSettings) -> Container:
    engine = make_engine(settings.db_url)
    upgrade_core(engine)
    sessions = sessionmaker(engine)

    def uow() -> UnitOfWork:
        # the Protocol declares plain attributes, which are invariant; SqlUnitOfWork narrows them
        return cast(UnitOfWork, SqlUnitOfWork(sessions))

    clock = SystemClock()
    bus = InMemoryEventBus()
    metrics = RingMetricsStore(maxlen=120, long_prefixes=LONG_PREFIXES, long_maxlen=LONG_MAXLEN)
    net = SystemNetworkTools()
    probes = SystemServiceProbes(local_ip=net.local_ip)
    system = SystemSystemInfo()
    snmp = PysnmpClient()
    vendors = OuiVendorLookup(settings.oui_file)
    registry = CapabilityRegistry()
    notifier = InMemoryStateNotifier()
    scheduler = AsyncScheduler(clock, on_job_finished=lambda _owner, _name, _ok: notifier.state_changed())

    with uow() as startup:
        startup.devices.clear_new()  # "New" means new since the last start
        # this device's own name, so it is never shown as a bare address (no event: it is not news)
        startup.identity.upsert_claim(
            NameClaim(SELF_KEY, net.hostname(), "hostname", NAME_RANKS["hostname"], clock.now_ms())
        )
        startup.commit()

    subnet = resolve_subnet(settings.subnet, net.local_ip())  # validates the configured subnet
    host_cache: tuple[float, str, str | None] | None = None  # (taken at, local ip, gateway)

    def current_subnet() -> IPv4Network:
        # a configured subnet is fixed; otherwise follow the network this device is on right now
        return subnet if settings.subnet else resolve_subnet(None, net.local_ip())

    def host_info() -> HostInfo:
        nonlocal host_cache
        now = time.monotonic()
        if host_cache is None or now - host_cache[0] > _HOST_TTL_S:
            ip = net.local_ip()
            host_cache = (now, ip, net.default_gateway(ip))
        _, ip, gateway = host_cache
        return HostInfo(net.hostname(), ip, gateway, str(resolve_subnet(settings.subnet, ip)), sys.platform)

    record = RecordSightings(uow, clock, vendors, bus, net.local_ip)
    claim = ClaimIdentity(uow, bus)
    scan = RunScan(registry, record, current_subnet, logging.getLogger("netview.scan"), net.local_ip)
    monitor = WatchMonitor(uow, bus, clock)
    ledger = TrafficLedger(metrics, clock)
    state = GetNetworkState(
        uow, registry, scheduler, host_info, vendors, monitor=monitor, ledger=ledger, subnet=current_subnet
    )
    device = GetDevice(uow, vendors)
    core = CoreFacade(state, device, uow, record, claim, scan, bus, clock, host_info)

    poll_health = PollHealth(HealthTargetsQuery(uow, host_info, current_subnet), metrics, monitor)
    poll_identity = PollIdentity(core.devices, claim, clock)
    poll_traffic = PollTraffic(ledger)

    def poller(plugin_id: str, capability: Capability, provider: object) -> JobSpec | None:
        """The core's own poll job for a provider of a polled capability (spec section 6)."""
        match capability:
            case Capability.HEALTH:
                health = cast(HealthProvider, provider)
                return JobSpec(
                    "poll.health", settings.fast_interval_s, lambda: poll_health(health), timeout_s=30
                )
            case Capability.IDENTITY:
                identity = cast(IdentityProvider, provider)
                return JobSpec(
                    "poll.identity",
                    _IDENTITY_INTERVAL_S,
                    lambda: poll_identity(plugin_id, identity),
                    timeout_s=120,
                    initial_delay_s=10,
                )
            case Capability.TRAFFIC:
                traffic = cast(TrafficProvider, provider)
                return JobSpec(
                    "poll.traffic",
                    settings.fast_interval_s,
                    lambda: poll_traffic(plugin_id, traffic),
                    timeout_s=15,
                )
            case _:
                return None

    def context_factory(plugin_id: str, plugin_settings: Any) -> DefaultPluginContext:
        return DefaultPluginContext(
            plugin_id, plugin_settings, engine, clock, net, vendors, metrics, core, bus, probes, system, snmp
        )

    folders = plugin_folders(settings)
    host = PluginHost(
        engine=engine,
        uow=uow,
        registry=registry,
        scheduler=scheduler,
        context_factory=context_factory,
        seeds=settings.plugins,
        discovered=discover_plugin_classes(extra_dirs=folders),
        folders=folders,
        poller=poller,
    )
    host.load_all()

    def recent_events(limit: int) -> list[DomainEvent]:
        with uow() as u:
            return u.events.recent(limit)

    def latest_inspection(ip: str) -> InspectionReport | None:
        with uow() as u:
            return u.inspections.latest(ip)

    user_themes = settings.data_dir / "themes"
    user_themes.mkdir(parents=True, exist_ok=True)
    themes = FolderThemeCatalog(WEB_STATIC / "themes", user_themes)

    services = AppServices(
        state=state,
        device=device,
        set_nickname=SetNickname(uow, clock, bus),
        forget_device=ForgetDevice(uow, bus, clock, metrics),
        add_watch=AddWatch(uow, bus, clock, forget=monitor.forget),
        remove_watch=RemoveWatch(uow, bus, clock, forget=monitor.forget),
        run_scan=scan,
        run_inspection=RunInspection(registry, uow, clock, bus),
        events=recent_events,
        latest_inspection=latest_inspection,
        plugins=host,
        bus=bus,
        scheduler=scheduler,
        notifier=notifier,
        themes=themes,
        metrics=metrics,
    )
    importer = LanmonImporter(uow, clock)
    return Container(settings, engine, subnet, registry, scheduler, host, core, services, importer, snmp)


def _scan_job(container: Container) -> Callable[[], None]:
    skipped: type[Exception] | None = None  # why the last run was skipped, so each state change logs once

    def run() -> None:
        nonlocal skipped
        try:
            container.services.run_scan()
        except ScanInProgressError:
            return  # another scan is running; this tick is not needed
        except (CapabilityUnavailableError, NoNetworkError) as exc:
            if skipped is not type(exc):  # say so once, not every interval
                log.warning("scheduled scan skipped: %s", exc)
                skipped = type(exc)
        else:
            skipped = None

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
            container.snmp.close()
            container.engine.dispose()

    allowed = {"localhost", "127.0.0.1", "[::1]", settings.bind}
    return create_app(
        container.services,
        container.host.routers(),
        container.host.ui_contributions(),
        allowed,
        lifespan=lifespan,
    )
