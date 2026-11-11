"""The public plugin SDK. Plugins import from here and nowhere else."""

from netview.application.capabilities import (
    Capability,
    DestinationsProvider,
    DiscoveryProvider,
    HealthProvider,
    HealthTargets,
    IdentityProvider,
    InspectionProvider,
    LocalHostProvider,
    TrafficProvider,
)
from netview.application.plugins.base import Plugin
from netview.application.plugins.context import PluginContext, PluginUnitOfWork
from netview.application.plugins.jobs import JobSpec
from netview.application.plugins.manifest import SDK_VERSION, Permission, PluginManifest
from netview.application.plugins.settings_layout import setting_group, settings_tabs
from netview.application.plugins.settings_requirements import (
    fixed_when,
    required_when,
    settings_requirements,
)
from netview.application.plugins.ui import StorageSpec, UiContribution
from netview.application.ports.network import PingResult, TcpResult
from netview.application.ports.probes import (
    CertInfo,
    DnsRecord,
    HttpProbe,
    NetbiosInfo,
    NetbiosName,
    ServiceProbes,
    SsdpEntry,
)
from netview.application.ports.snmp import (
    Oid,
    SnmpAuthError,
    SnmpClient,
    SnmpError,
    SnmpTarget,
    SnmpTimeout,
    SnmpV2c,
    SnmpV3,
    SnmpValue,
    parse_oid,
)
from netview.application.ports.system import SystemInfo, TcpSocket, WifiInfo
from netview.application.queries.read_models import DeviceView, HostInfo
from netview.application.usecases.traffic import TrafficTotals, TrafficView
from netview.domain.device_kind import os_hint, vendor_type
from netview.domain.events import EventKind
from netview.domain.inspection import ReportSection
from netview.domain.naming import NAME_RANKS, TYPE_RANKS, Hint, NameClaim, TypeClaim
from netview.domain.samples import Flow, LatencySample, Sighting, TrafficReading, counter_rate
from netview.domain.watch import Watch, WatchProbe, WatchState, WatchStatus

__all__ = [
    "NAME_RANKS",
    "SDK_VERSION",
    "TYPE_RANKS",
    "Capability",
    "CertInfo",
    "DestinationsProvider",
    "DeviceView",
    "DiscoveryProvider",
    "DnsRecord",
    "EventKind",
    "Flow",
    "HealthProvider",
    "HealthTargets",
    "Hint",
    "HostInfo",
    "HttpProbe",
    "IdentityProvider",
    "InspectionProvider",
    "JobSpec",
    "LatencySample",
    "LocalHostProvider",
    "NameClaim",
    "NetbiosInfo",
    "NetbiosName",
    "Oid",
    "Permission",
    "PingResult",
    "Plugin",
    "PluginContext",
    "PluginManifest",
    "PluginUnitOfWork",
    "ReportSection",
    "ServiceProbes",
    "Sighting",
    "SnmpAuthError",
    "SnmpClient",
    "SnmpError",
    "SnmpTarget",
    "SnmpTimeout",
    "SnmpV2c",
    "SnmpV3",
    "SnmpValue",
    "SsdpEntry",
    "StorageSpec",
    "SystemInfo",
    "TcpResult",
    "TcpSocket",
    "TrafficProvider",
    "TrafficReading",
    "TrafficTotals",
    "TrafficView",
    "TypeClaim",
    "UiContribution",
    "Watch",
    "WatchProbe",
    "WatchState",
    "WatchStatus",
    "WifiInfo",
    "counter_rate",
    "fixed_when",
    "os_hint",
    "parse_oid",
    "required_when",
    "setting_group",
    "settings_requirements",
    "settings_tabs",
    "vendor_type",
]
