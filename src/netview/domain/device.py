"""Device entity."""

from dataclasses import dataclass
from enum import StrEnum


class DeviceStatus(StrEnum):
    ONLINE = "online"
    QUIET = "quiet"
    OFFLINE = "offline"


@dataclass
class Device:
    key: str
    ip: str
    mac: str | None
    vendor: str
    first_seen_ms: int
    last_seen_ms: int
    status: DeviceStatus
    rtt_ms: float | None = None
    ttl: int | None = None
    is_self: bool = False
    missed: int = 0
    is_new: bool = False
