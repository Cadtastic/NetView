"""Capability identifiers and the provider contracts plugins implement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from ipaddress import IPv4Network
from typing import TYPE_CHECKING, Any, Protocol

from netview.domain.inspection import ReportSection
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.samples import Flow, LatencySample, Sighting, TrafficReading

if TYPE_CHECKING:
    from netview.application.queries.read_models import DeviceView


class Capability(StrEnum):
    DISCOVERY = "discovery"
    IDENTITY = "identity"
    HEALTH = "health"
    TRAFFIC = "traffic"
    DESTINATIONS = "destinations"
    INSPECTION = "inspection"
    LOCAL_HOST = "local_host"
    API = "api"
    WEB_UI = "web_ui"
    STORAGE = "storage"
    JOBS = "jobs"


class DiscoveryProvider(Protocol):
    def discover(self, subnet: IPv4Network) -> Iterable[Sighting]: ...


class IdentityProvider(Protocol):
    recheck_after_s: float

    def identify(self, device: DeviceView) -> Iterable[NameClaim | TypeClaim | Hint]: ...


class HealthProvider(Protocol):
    def probe(self) -> Iterable[LatencySample]: ...


class TrafficProvider(Protocol):
    def read(self) -> Iterable[TrafficReading]: ...


class DestinationsProvider(Protocol):
    def read(self) -> Iterable[Flow]: ...


class InspectionProvider(Protocol):
    def inspect(self, ip: str, ports_spec: str) -> Iterable[ReportSection]: ...


class LocalHostProvider(Protocol):
    def snapshot(self) -> Mapping[str, Any]: ...
