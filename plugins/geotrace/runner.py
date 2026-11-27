"""One GeoTrace run: resolve, traceroute, ping burst, place hops, save, change events (spec 6.2)."""

from __future__ import annotations

import itertools
import socket
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from netview.sdk import EventKind, TraceHop

from .addresses import ResolveError, resolve
from .changes import ChangeTracker, signature_json
from .geo import HopLocator
from .model import Hop, Target, Trace
from .placement import Home, place_hops
from .storage import TraceStore

MAX_HOPS = 30
PROBE_TIMEOUT_MS = 1000
PINGS = 10
PING_GAP_S = 0.2
PING_TIMEOUT_MS = 800
RECENT_WINDOW_MS = 25 * 3_600_000


@dataclass(frozen=True)
class Job:
    target_id: int | None
    address: str
    family: str
    trigger: str  # scheduled | manual | once
    mode: str  # trace | ping
    name: str


@dataclass(frozen=True)
class LiveSnapshot:
    id: int
    status: str
    hops: tuple[Hop, ...]
    error: str | None
    started_ms: int


@dataclass
class LiveTrace:
    """What a running trace looks like right now. The worker writes, the API thread reads."""

    id: int
    started_ms: int
    status: str = "queued"
    error: str | None = None
    target_id: int | None = None
    mode: str = "trace"
    trigger: str = ""
    _hops: list[Hop] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def hops(self) -> list[Hop]:
        with self._lock:
            return list(self._hops)

    def update(
        self, *, status: str | None = None, error: str | None = None, hops: Sequence[Hop] | None = None
    ) -> None:
        with self._lock:
            if status is not None:
                self.status = status
            if error is not None:
                self.error = error
            if hops is not None:
                self._hops = list(hops)

    def snapshot(self) -> LiveSnapshot:
        with self._lock:
            return LiveSnapshot(self.id, self.status, tuple(self._hops), self.error, self.started_ms)


@dataclass(frozen=True)
class _Burst:
    rtts: list[float]
    loss_pct: float
    avg: float | None
    low: float | None
    high: float | None
    jitter: float | None


def _burst(rtts: list[float], sent: int) -> _Burst:
    loss = round(100.0 * (sent - len(rtts)) / sent, 1) if sent else 100.0
    if not rtts:
        return _Burst([], 100.0, None, None, None, None)
    jitter = sum(abs(b - a) for a, b in itertools.pairwise(rtts)) / (len(rtts) - 1) if len(rtts) > 1 else 0.0
    return _Burst(rtts, loss, sum(rtts) / len(rtts), min(rtts), max(rtts), jitter)


class _Stopped(Exception):
    """The service is shutting down: abandon the run (raised from on_hop, so the core stops the child)."""


STOPPED = "GeoTrace was stopped"
INTERNAL_ERROR = "The trace stopped because of an internal error."  # the detail goes to the log only


class TraceRunner:
    def __init__(
        self,
        ctx: Any,
        traces: TraceStore,
        tracker: ChangeTracker,
        home_fn: Callable[[], Home | None],
        locator_fn: Callable[[], HopLocator | None],
        sleep: Callable[[float], None] = time.sleep,
        getaddrinfo: Callable[..., Any] = socket.getaddrinfo,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._ctx = ctx
        self._traces = traces
        self._tracker = tracker
        self._home_fn = home_fn
        self._locator_fn = locator_fn
        self._sleep = sleep
        self._getaddrinfo = getaddrinfo
        self._should_stop = should_stop

    def _check_stop(self) -> None:
        if self._should_stop():
            raise _Stopped

    def run(self, job: Job, live: LiveTrace) -> Trace:
        """Run one trace. Never raises: any failure becomes a saved failed trace.

        If the save itself fails the live trace is marked failed and the unsaved trace
        (id 0) is returned, so a caller polling the live trace never waits forever.
        When ``should_stop`` turns true the run is abandoned the same way (error "GeoTrace was stopped"):
        nothing is saved and no event is raised.
        """
        ctx = self._ctx
        live.update(status="running")
        resolved: str | None = None
        placed: tuple[Hop, ...] = ()
        reached = False
        error: str | None = None
        burst = _burst([], 0)

        try:
            # The locator is fetched once per run: a monthly database swap closes older ones.
            home = self._home_fn()
            locator = self._locator_fn()
            raw: list[TraceHop] = []

            def on_hop(hop: TraceHop) -> None:
                self._check_stop()
                raw.append(hop)
                live.update(hops=place_hops(raw, home, locator))

            try:
                resolved = resolve(job.address, job.family, self._getaddrinfo)
            except ResolveError as e:
                error = str(e)

            if error is None and resolved is not None:
                if job.mode == "trace":
                    result = ctx.net.traceroute(resolved, MAX_HOPS, PROBE_TIMEOUT_MS, on_hop)
                    raw = list(result.hops)
                    reached = result.reached
                    error = result.error
                    placed = place_hops(raw, home, locator)
                    live.update(hops=placed)
                self._check_stop()
                if error is None:
                    burst = self._ping_burst(resolved)
                    if job.mode == "ping":
                        reached = burst.avg is not None
                        # Ping only shows just the destination on the globe.
                        shown = tuple(burst.rtts[:3]) or (None,)
                        placed = place_hops([TraceHop(1, resolved, shown)], home, locator)
                        live.update(hops=placed)
        except _Stopped:
            error = STOPPED
            reached = False
            burst = _burst([], 0)
        except Exception as e:
            ctx.log.exception("GeoTrace run failed")
            error = INTERNAL_ERROR
            reached = False
            burst = _burst([], 0)

        finished = ctx.clock.now_ms()
        failed = error is not None
        trace = Trace(
            id=0,
            target_id=job.target_id,
            trigger=job.trigger,
            mode=job.mode,
            status="failed" if failed else "done",
            error=error,
            started_ms=live.started_ms,
            finished_ms=finished,
            resolved_ip=resolved,
            family=job.family,
            reached=reached and not failed,
            hop_count=len(placed),
            rtt_ms=burst.avg,
            loss_pct=burst.loss_pct if not failed else None,
            jitter_ms=burst.jitter,
            ping_min_ms=burst.low,
            ping_max_ms=burst.high,
            signature=signature_json(placed),
            hops=placed,
        )
        if error == STOPPED or self._should_stop():
            live.update(status="failed", error=STOPPED)
            return replace(trace, status="failed", error=STOPPED, reached=False)
        try:
            recent = self._recent_rtts(job.target_id, finished)
            trace = replace(trace, id=self._traces.save(trace))
        except Exception as e:
            ctx.log.exception("GeoTrace could not save a trace")
            message = INTERNAL_ERROR
            live.update(status="failed", error=message)
            return replace(trace, status="failed", error=message, reached=False)
        live.update(status=trace.status, error=error)
        try:
            self._check_stop()
            self._raise_events(job, trace, recent, resolved)
        except _Stopped:
            pass
        except Exception:
            ctx.log.exception("GeoTrace could not raise change events")
        return trace

    def _ping_burst(self, ip: str) -> _Burst:
        rtts: list[float] = []
        for i in range(PINGS):
            self._check_stop()
            if i:
                self._sleep(PING_GAP_S)
            reply = self._ctx.net.ping(ip, PING_TIMEOUT_MS)
            if reply is not None:
                rtts.append(reply.rtt_ms)
        return _burst(rtts, PINGS)

    def _recent_rtts(self, target_id: int | None, now: int) -> list[tuple[int, float]]:
        if target_id is None:
            return []
        return [
            (t.finished_ms or t.started_ms, t.rtt_ms)
            for t in self._traces.between(target_id, now - RECENT_WINDOW_MS, now)
            if t.status == "done" and t.rtt_ms is not None
        ]

    def _raise_events(self, job: Job, trace: Trace, recent: list[tuple[int, float]], ip: str | None) -> None:
        if job.target_id is None or job.trigger == "once" or job.mode == "ping":
            return
        target = Target(job.target_id, job.name, job.address, job.family, 0, True, 0, 0)
        for text in self._tracker.observe(target, trace, recent):
            self._ctx.core.add_event(EventKind.PLUGIN, text, ip=ip)
