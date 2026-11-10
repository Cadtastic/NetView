"""Measurement value objects."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Sighting:
    ip: str
    mac: str | None
    rtt_ms: float | None
    ttl: int | None
    seen_ms: int


@dataclass(frozen=True)
class LatencySample:
    series: str
    t_ms: int
    rtt_ms: float | None


@dataclass(frozen=True)
class TrafficReading:
    ip: str
    t_ms: int
    down_bytes: int
    up_bytes: int
    extra: Mapping[str, Any]


@dataclass(frozen=True)
class Flow:
    device_ip: str
    remote: str
    port: int
    proto: str
    bytes: int
    t_ms: int
    dns_name: str | None
