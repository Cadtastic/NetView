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


def counter_rate(
    prev: tuple[int, int, int] | None, down_bytes: int, up_bytes: int, t_ms: int
) -> tuple[float, float] | None:
    """Bits per second between two byte-counter readings.

    ``prev`` is ``(down, up, t_ms)``. Returns ``None`` when there is no earlier reading, no time has
    passed, or either counter went backwards (the device reconnected or the router rebooted).
    """
    if prev is None:
        return None
    prev_down, prev_up, prev_t = prev
    dt_s = (t_ms - prev_t) / 1000
    if dt_s <= 0 or down_bytes < prev_down or up_bytes < prev_up:
        return None
    return ((down_bytes - prev_down) * 8 / dt_s, (up_bytes - prev_up) * 8 / dt_s)
