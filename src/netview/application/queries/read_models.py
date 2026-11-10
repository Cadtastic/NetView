"""Read models returned by queries and handed to plugins and presentation."""

from dataclasses import dataclass

from netview.application.plugins.jobs import JobStatus
from netview.domain.events import DomainEvent
from netview.domain.watch import Watch


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
