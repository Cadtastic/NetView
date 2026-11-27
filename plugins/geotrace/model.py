"""GeoTrace's value types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    id: int
    name: str
    address: str
    family: str
    interval_min: int
    enabled: bool
    created_ms: int
    updated_ms: int


@dataclass(frozen=True)
class Hop:
    n: int
    ip: str | None
    rtts_ms: tuple[float | None, ...]
    city: str
    region: str
    country: str
    lat: float | None
    lon: float | None
    asn: int | None
    as_org: str
    placement: str  # located | home | assumed | none
    plausible: bool


@dataclass(frozen=True)
class Trace:
    id: int
    target_id: int | None
    trigger: str  # scheduled | manual | once
    mode: str  # trace | ping
    status: str  # queued | running | done | failed
    error: str | None
    started_ms: int
    finished_ms: int | None
    resolved_ip: str | None
    family: str
    reached: bool
    hop_count: int
    rtt_ms: float | None
    loss_pct: float | None
    jitter_ms: float | None
    ping_min_ms: float | None
    ping_max_ms: float | None
    signature: str  # JSON [[asn, city], ...]
    hops: tuple[Hop, ...]
