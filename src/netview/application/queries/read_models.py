"""Read models returned by queries and handed to plugins and presentation."""

from dataclasses import dataclass, field

from netview.application.plugins.jobs import JobStatus
from netview.application.usecases.traffic import TrafficTotals, TrafficView
from netview.domain.events import DomainEvent
from netview.domain.watch import Watch, WatchStatus


@dataclass(frozen=True)
class DeviceView:
    key: str
    ip: str
    mac: str | None
    vendor: str
    nickname: str | None
    device_name: str
    name_source: str
    type: str
    hints: list[str]
    status: str
    rtt_ms: float | None
    ttl: int | None
    first_seen_ms: int
    last_seen_ms: int
    is_new: bool
    is_self: bool
    watched: bool
    display_name: str
    type_source: str = ""
    """Where ``type`` came from (``"inspection"``, ``"vendor"`` or a plugin id); '' when there is no type."""


@dataclass(frozen=True)
class HostInfo:
    hostname: str
    ip: str
    gateway: str | None
    subnet: str
    platform: str


@dataclass(frozen=True)
class NetworkState:
    host: HostInfo
    devices: list[DeviceView]
    events: list[DomainEvent]
    watches: list[Watch]
    capabilities: list[str]
    jobs: list[JobStatus]
    watch_status: list[WatchStatus] = field(default_factory=list)
    traffic: list[TrafficView] = field(default_factory=list)
    traffic_totals: list[TrafficTotals] = field(default_factory=list)
    inspected: dict[str, int] = field(default_factory=dict)
    """IP -> ``finished_ms`` of its newest inspection report."""
