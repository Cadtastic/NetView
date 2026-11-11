"""The public plugin SDK. Plugins import from here and nowhere else."""

from netview.application.capabilities import (
    Capability,
    DestinationsProvider,
    DiscoveryProvider,
    HealthProvider,
    IdentityProvider,
    InspectionProvider,
    LocalHostProvider,
    TrafficProvider,
)
from netview.application.plugins.base import Plugin
from netview.application.plugins.context import PluginContext, PluginUnitOfWork
from netview.application.plugins.jobs import JobSpec
from netview.application.plugins.manifest import SDK_VERSION, Permission, PluginManifest
from netview.application.plugins.ui import StorageSpec, UiContribution
from netview.application.ports.network import PingResult, TcpResult
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
from netview.application.queries.read_models import DeviceView
from netview.domain.events import EventKind
from netview.domain.inspection import ReportSection
from netview.domain.naming import NAME_RANKS, Hint, NameClaim, TypeClaim
from netview.domain.samples import Flow, LatencySample, Sighting, TrafficReading

__all__ = [
    "NAME_RANKS",
    "SDK_VERSION",
    "Capability",
    "DestinationsProvider",
    "DeviceView",
    "DiscoveryProvider",
    "EventKind",
    "Flow",
    "HealthProvider",
    "Hint",
    "IdentityProvider",
    "InspectionProvider",
    "JobSpec",
    "LatencySample",
    "LocalHostProvider",
    "NameClaim",
    "Oid",
    "Permission",
    "PingResult",
    "Plugin",
    "PluginContext",
    "PluginManifest",
    "PluginUnitOfWork",
    "ReportSection",
    "Sighting",
    "SnmpAuthError",
    "SnmpClient",
    "SnmpError",
    "SnmpTarget",
    "SnmpTimeout",
    "SnmpV2c",
    "SnmpV3",
    "SnmpValue",
    "StorageSpec",
    "TcpResult",
    "TrafficProvider",
    "TrafficReading",
    "TypeClaim",
    "UiContribution",
    "parse_oid",
]
