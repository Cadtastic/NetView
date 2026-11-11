"""Health: latency series, and watch statuses with their change events."""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from ipaddress import IPv4Network
from typing import TYPE_CHECKING

from netview.application.capabilities import HealthTargets
from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.metrics import MetricsStore
from netview.application.ports.uow import UnitOfWorkFactory
from netview.application.queries.read_models import HostInfo
from netview.domain.device import DeviceStatus
from netview.domain.events import DomainEvent, EventKind
from netview.domain.keys import SELF_KEY
from netview.domain.samples import LatencySample
from netview.domain.watch import (
    WATCH_LABELS,
    Watch,
    WatchProbe,
    WatchState,
    WatchStatus,
    assess_watch,
)

if TYPE_CHECKING:
    from netview.application.capabilities import HealthProvider

MAX_DEVICE_TARGETS = 64  # LM 1383
HISTORY_LEN = 60  # LM 1377
_HISTORY_VALUE = {WatchState.UP: 1.0, WatchState.DEGRADED: 0.5}
_WAITING = "Waiting for the first check."


@dataclass
class _Entry:
    ports: tuple[int, ...]
    state: WatchState
    since_ms: int
    checked_ms: int
    probe: WatchProbe
    diagnosis: str
    history: list[float] = field(default_factory=list)


def _ip_key(ip: str) -> tuple[int, int, str]:
    try:
        return (0, int(ipaddress.IPv4Address(ip)), ip)
    except ValueError:
        return (1, 0, ip)


def _on_subnet(ip: str, subnet: IPv4Network) -> bool:
    try:
        return ipaddress.IPv4Address(ip) in subnet
    except ValueError:
        return False


class WatchMonitor:
    """Latest result per watch. A watch that was removed, or whose ports changed, starts over. Thread-safe."""

    def __init__(self, uow: UnitOfWorkFactory, bus: EventBus, clock: Clock) -> None:
        self._uow = uow
        self._bus = bus
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._reset_ms: dict[str, int] = {}

    def forget(self, ip: str) -> None:
        """A watch was added or removed: drop its result and ignore probes checked before now."""
        with self._lock:
            self._entries.pop(ip, None)
            self._reset_ms[ip] = self._clock.now_ms()

    def record(self, probes: Iterable[WatchProbe]) -> None:
        events: list[DomainEvent] = []
        with self._lock, self._uow() as uow:
            watches = {w.ip: w for w in uow.watches.list()}
            self._prune(watches.values())
            for probe in probes:
                watch = watches.get(probe.ip)
                if watch is None:
                    continue  # removed since the probe started
                if probe.checked_ms < self._reset_ms.get(probe.ip, probe.checked_ms):
                    continue  # checked before the watch was removed or re-added
                state, diagnosis = assess_watch(watch, probe)
                entry = self._entries.get(probe.ip)
                old = entry.state if entry is not None else WatchState.PENDING
                since = entry.since_ms if entry is not None else probe.checked_ms
                history = entry.history if entry is not None else []
                if state != old:
                    since = probe.checked_ms
                    if not (old is WatchState.PENDING and state is WatchState.UP):
                        events.append(
                            DomainEvent(
                                EventKind.WATCH,
                                f"{watch.label or watch.ip} is now {WATCH_LABELS[state]} "
                                f"(was {WATCH_LABELS[old]})",
                                self._clock.now_ms(),
                                watch.ip,
                            )
                        )
                history = [*history, _HISTORY_VALUE.get(state, 0.0)][-HISTORY_LEN:]
                self._entries[probe.ip] = _Entry(
                    watch.ports, state, since, probe.checked_ms, probe, diagnosis, history
                )
            for e in events:
                uow.events.add(e)
            if events:
                uow.commit()
        for e in events:
            self._bus.publish(e)

    def statuses(self, watches: Sequence[Watch], subnet: IPv4Network) -> list[WatchStatus]:
        with self._lock:
            # No pruning here: `watches` may be older than a watch added since, whose fresh result
            # must survive. record() prunes against the list it reads, and forget() handles removals.
            out: list[WatchStatus] = []
            for w in sorted(watches, key=lambda w: _ip_key(w.ip)):
                entry = self._entries.get(w.ip)
                if entry is None or entry.ports != w.ports:  # none yet, or for other ports
                    out.append(
                        WatchStatus(
                            w.ip,
                            w.label,
                            w.ports,
                            WatchState.PENDING,
                            None,
                            None,
                            _on_subnet(w.ip, subnet),
                            None,
                            None,
                            None,
                            {},
                            _WAITING,
                            (),
                        )
                    )
                    continue
                p = entry.probe
                out.append(
                    WatchStatus(
                        w.ip,
                        w.label,
                        w.ports,
                        entry.state,
                        entry.since_ms,
                        entry.checked_ms,
                        p.on_subnet,
                        p.l2,
                        p.mac,
                        p.rtt_ms,
                        dict(p.ports),
                        entry.diagnosis,
                        tuple(entry.history),
                    )
                )
            return out

    def _prune(self, watches: Iterable[Watch]) -> None:
        """Forget the results of watches that are gone or now watch other ports. Caller holds the lock."""
        current = {w.ip: w.ports for w in watches}
        for ip in [ip for ip, e in self._entries.items() if current.get(ip) != e.ports]:
            del self._entries[ip]


class PollHealth:
    def __init__(
        self, targets: Callable[[], HealthTargets], metrics: MetricsStore, monitor: WatchMonitor
    ) -> None:
        self._targets = targets
        self._metrics = metrics
        self._monitor = monitor

    def __call__(self, provider: HealthProvider) -> None:
        probes: list[WatchProbe] = []
        for item in provider.probe(self._targets()):
            if isinstance(item, LatencySample):
                self._metrics.append(item.series, item.t_ms, item.rtt_ms)
            else:
                probes.append(item)
        if probes:
            self._monitor.record(probes)


class HealthTargetsQuery:
    def __init__(
        self, uow: UnitOfWorkFactory, host: Callable[[], HostInfo], subnet: Callable[[], IPv4Network]
    ) -> None:
        self._uow = uow
        self._host = host
        self._subnet = subnet

    def __call__(self) -> HealthTargets:
        with self._uow() as uow:
            online = [
                (d.key, d.ip)
                for d in uow.devices.list()
                if d.status is DeviceStatus.ONLINE and not d.is_self and d.key != SELF_KEY
            ]
            watches = tuple(uow.watches.list())
        online.sort(key=lambda kv: _ip_key(kv[1]))
        return HealthTargets(
            gateway=self._host().gateway,
            subnet=self._subnet(),
            devices=tuple(online[:MAX_DEVICE_TARGETS]),
            watches=watches,
        )
