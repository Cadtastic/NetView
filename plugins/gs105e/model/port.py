"""Per-port status, raw counters and derived rates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PortStatus:
    port: int
    description: str
    up: bool
    speed_setting: str  # the text the switch shows: "Auto", "Disable", "10M Half", ...
    link_mbps: int | None
    flow_control: bool
    max_mtu: int | None


@dataclass(frozen=True, slots=True)
class PortCounters:
    port: int
    t_ms: int
    rx_bytes: int
    tx_bytes: int
    crc_errors: int


@dataclass(frozen=True, slots=True)
class PortRates:
    """``in`` means received by the switch port."""

    port: int
    t_ms: int
    in_bps: float
    out_bps: float
    crc_delta: int
    util_percent: float | None
