"""Ports, their counters and the rates derived from them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Duplex = Literal["full", "half", "unknown"]
PortKind = Literal["ethernet", "lag", "other"]


@dataclass(frozen=True, slots=True)
class Port:
    if_index: int
    name: str
    alias: str
    kind: PortKind
    admin_up: bool
    oper_up: bool
    speed_mbps: int | None
    duplex: Duplex
    last_change_cs: int


@dataclass(frozen=True, slots=True)
class PortCounters:
    if_index: int
    t_ms: int
    hc: bool
    in_octets: int
    out_octets: int
    in_ucast: int
    out_ucast: int
    in_mcast: int
    out_mcast: int
    in_bcast: int
    out_bcast: int
    in_errors: int
    out_errors: int
    in_discards: int
    out_discards: int


@dataclass(frozen=True, slots=True)
class PortRates:
    if_index: int
    t_ms: int
    in_bps: float
    out_bps: float
    in_err_ps: float
    out_err_ps: float
    in_disc_ps: float
    out_disc_ps: float
    util_percent: float | None
