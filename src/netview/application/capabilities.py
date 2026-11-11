"""Capability identifiers and the provider contracts plugins implement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Network
from typing import TYPE_CHECKING, Any, Protocol

from netview.domain.inspection import ReportSection
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.samples import Flow, LatencySample, Sighting, TrafficReading
from netview.domain.watch import Watch, WatchProbe

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
    """Seconds before the core hands the same device to this provider again."""

    def identify(self, devices: Sequence[DeviceView]) -> Iterable[NameClaim | TypeClaim | Hint]:
        """Learn names, types and hints for ``devices`` (non-self, not offline, at most 128 per run)."""
        ...


@dataclass(frozen=True)
class HealthTargets:
    """What a health provider should measure this round."""

    gateway: str | None
    subnet: IPv4Network
    devices: tuple[tuple[str, str], ...]
    """``(key, ip)`` of online, non-self devices, at most 64, in IP order."""
    watches: tuple[Watch, ...]


class HealthProvider(Protocol):
    def probe(self, targets: HealthTargets) -> Iterable[LatencySample | WatchProbe]:
        """Measure ``targets``. A ping with no reply is a ``LatencySample`` with ``rtt_ms=None``."""
        ...


class TrafficProvider(Protocol):
    def read(self) -> Iterable[TrafficReading]:
        """Byte counters per client IP (``None`` counters: listed, but no counters given).

        Keys of ``TrafficReading.extra`` the core uses: ``name``, ``role``,
        ``signal_dbm``, ``down_link``, ``up_link``, ``assoc_s`` and ``ap``; others are passed through."""
        ...


class DestinationsProvider(Protocol):
    def read(self) -> Iterable[Flow]: ...


class InspectionProvider(Protocol):
    def inspect(self, ip: str, ports_spec: str) -> Iterable[ReportSection]:
        """Inspect one device. ``ports_spec`` is ``"top"`` (the usual few dozen ports), ``"all"``
        (1-65535), ``"common"`` (a short list for the quick probe) or a comma list of ports and
        ranges such as ``"22,80,8000-8100"``."""
        ...


class LocalHostProvider(Protocol):
    def snapshot(self) -> Mapping[str, Any]: ...
