"""Per-client traffic: turn byte counters from traffic providers into rates, series and totals."""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from netview.application.ports.clock import Clock
from netview.application.ports.metrics import MetricsStore
from netview.domain.samples import TrafficReading, counter_rate

if TYPE_CHECKING:
    from netview.application.capabilities import TrafficProvider

_STALE_MS = 600_000  # an IP unseen for this long is dropped (LM 1461)
_SERIES_LIMIT = 120


@dataclass(frozen=True)
class TrafficView:
    ip: str
    source: str
    down_bps: float | None
    up_bps: float | None
    down_avg_bps: float | None
    up_avg_bps: float | None
    down_total: int | None
    up_total: int | None
    seen_ms: int
    extra: Mapping[str, Any]


@dataclass(frozen=True)
class TrafficTotals:
    source: str
    clients: int
    down_bps: float
    up_bps: float
    t_ms: int


@dataclass
class _Entry:
    source: str
    last: tuple[int, int, int] | None  # (down bytes, up bytes, t_ms) of the newest reading that had counters
    down_bps: float | None
    up_bps: float | None
    seen_ms: int
    extra: Mapping[str, Any]


def _down(ip: str) -> str:
    return f"traffic.down.{ip}"


def _up(ip: str) -> str:
    return f"traffic.up.{ip}"


def _ip_key(ip: str) -> tuple[int, int, str]:
    try:
        return (0, int(ipaddress.IPv4Address(ip)), ip)
    except ValueError:
        return (1, 0, ip)


class TrafficLedger:
    """The latest reading and rate of every client a traffic provider reports. Thread-safe."""

    def __init__(self, metrics: MetricsStore, clock: Clock | None = None) -> None:
        self._metrics = metrics
        self._clock = clock  # when given, expiry also applies when reading, not only when recording
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._totals: dict[str, TrafficTotals] = {}
        self._now_ms = 0

    def record(self, source: str, readings: Iterable[TrafficReading]) -> None:
        batch = list(readings)
        with self._lock:
            if batch:
                self._now_ms = max(self._now_ms, max(r.t_ms for r in batch))
            down_sum = up_sum = 0.0
            for r in batch:
                entry = self._entries.get(r.ip)
                prev = entry.last if entry is not None else None
                if r.down_bytes is None or r.up_bytes is None:
                    # listed without counters: no rate, and the earlier counters stay the reference
                    last, down_bps, up_bps = prev, None, None
                else:
                    last = (r.down_bytes, r.up_bytes, r.t_ms)
                    rate = counter_rate(prev, r.down_bytes, r.up_bytes, r.t_ms)
                    down_bps, up_bps = rate if rate is not None else (None, None)
                self._metrics.append(_down(r.ip), r.t_ms, down_bps)
                self._metrics.append(_up(r.ip), r.t_ms, up_bps)
                if down_bps is not None and up_bps is not None:
                    down_sum += down_bps
                    up_sum += up_bps
                self._entries[r.ip] = _Entry(source, last, down_bps, up_bps, r.t_ms, r.extra)
            self._expire(self._now_ms)
            clients = len({r.ip for r in batch})
            stamp = self._clock.now_ms() if self._clock is not None else self._now_ms
            self._totals[source] = TrafficTotals(source, clients, down_sum, up_sum, stamp)

    def views(self) -> list[TrafficView]:
        with self._lock:
            self._expire_at_read()
            entries = sorted(self._entries.items(), key=lambda kv: _ip_key(kv[0]))
        return [self._view(ip, e) for ip, e in entries]

    def totals(self) -> list[TrafficTotals]:
        with self._lock:
            self._expire_at_read()
            return sorted(self._totals.values(), key=lambda t: t.source)

    def _expire_at_read(self) -> None:
        """Caller holds the lock. Without a clock only record() expires things."""
        if self._clock is not None:
            self._expire(self._clock.now_ms())

    def _expire(self, now_ms: int) -> None:
        """Drop clients (and their series) and sources unseen for over ten minutes. Caller holds the lock."""
        for ip in [ip for ip, e in self._entries.items() if now_ms - e.seen_ms > _STALE_MS]:
            del self._entries[ip]
            self._metrics.drop(_down(ip))
            self._metrics.drop(_up(ip))
        for source in [s for s, t in self._totals.items() if now_ms - t.t_ms > _STALE_MS]:
            del self._totals[source]

    def _view(self, ip: str, e: _Entry) -> TrafficView:
        return TrafficView(
            ip=ip,
            source=e.source,
            down_bps=e.down_bps,
            up_bps=e.up_bps,
            down_avg_bps=self._average(_down(ip)),
            up_avg_bps=self._average(_up(ip)),
            down_total=e.last[0] if e.last is not None else None,
            up_total=e.last[1] if e.last is not None else None,
            seen_ms=e.seen_ms,
            extra=e.extra,
        )

    def _average(self, series: str) -> float | None:
        values = [v for _, v in self._metrics.series(series, _SERIES_LIMIT) if v is not None]
        return sum(values) / len(values) if values else None


class PollTraffic:
    def __init__(self, ledger: TrafficLedger) -> None:
        self._ledger = ledger

    def __call__(self, source: str, provider: TrafficProvider) -> None:
        self._ledger.record(source, provider.read())
