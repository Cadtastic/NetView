"""In-memory implementations of the application ports, for tests and plugin authors."""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from types import TracebackType

from netview.application.ports.network import PingResult, TcpResult
from netview.application.ports.repositories import PluginState
from netview.domain.device import Device
from netview.domain.events import DomainEvent
from netview.domain.inspection import InspectionReport
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.nickname import NicknameChange
from netview.domain.watch import Watch


@dataclass
class _Store:
    devices: dict[str, Device] = field(default_factory=dict)
    claims: dict[tuple[str, str], NameClaim] = field(default_factory=dict)
    types: dict[tuple[str, str], TypeClaim] = field(default_factory=dict)
    hints: dict[tuple[str, str], list[Hint]] = field(default_factory=dict)
    nicknames: dict[str, str] = field(default_factory=dict)
    nickname_history: list[NicknameChange] = field(default_factory=list)
    watches: dict[str, Watch] = field(default_factory=dict)
    events: list[DomainEvent] = field(default_factory=list)
    inspections: dict[str, InspectionReport] = field(default_factory=dict)
    plugin_state: dict[str, PluginState] = field(default_factory=dict)


class _Devices:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def get(self, key: str) -> Device | None:
        return self._s.devices.get(key)

    def get_by_ip(self, ip: str) -> Device | None:
        return next((d for d in self._s.devices.values() if d.ip == ip), None)

    def list(self) -> list[Device]:
        return list(self._s.devices.values())

    def add(self, device: Device) -> None:
        self._s.devices[device.key] = device

    def save(self, device: Device) -> None:
        self._s.devices[device.key] = device

    def remove(self, key: str) -> None:
        self._s.devices.pop(key, None)


class _Identity:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def claims(self, key: str) -> list[NameClaim]:
        return [c for (k, _), c in self._s.claims.items() if k == key]

    def all_claims(self) -> dict[str, list[NameClaim]]:
        out: dict[str, list[NameClaim]] = defaultdict(list)
        for (k, _), c in self._s.claims.items():
            out[k].append(c)
        return dict(out)

    def upsert_claim(self, c: NameClaim) -> None:
        self._s.claims[(c.key, c.source)] = c

    def types(self, key: str) -> list[TypeClaim]:
        return [t for (k, _), t in self._s.types.items() if k == key]

    def upsert_type(self, t: TypeClaim) -> None:
        self._s.types[(t.key, t.source)] = t

    def hints(self, key: str) -> list[Hint]:
        return [h for (k, _), hs in self._s.hints.items() if k == key for h in hs]

    def replace_hints(self, key: str, source: str, hints: list[Hint]) -> None:
        self._s.hints[(key, source)] = list(hints)

    def rekey(self, old: str, new: str) -> None:
        for (k, src), c in list(self._s.claims.items()):
            if k == old:
                del self._s.claims[(k, src)]
                self._s.claims[(new, src)] = replace(c, key=new)
        for (k, src), t in list(self._s.types.items()):
            if k == old:
                del self._s.types[(k, src)]
                self._s.types[(new, src)] = replace(t, key=new)
        for (k, src), hs in list(self._s.hints.items()):
            if k == old:
                del self._s.hints[(k, src)]
                self._s.hints[(new, src)] = [replace(h, key=new) for h in hs]


class _Nicknames:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def get(self, key: str) -> str | None:
        return self._s.nicknames.get(key)

    def all(self) -> dict[str, str]:
        return dict(self._s.nicknames)

    def set(self, key: str, value: str | None) -> None:
        if value:
            self._s.nicknames[key] = value
        else:
            self._s.nicknames.pop(key, None)

    def add_history(self, c: NicknameChange) -> None:
        self._s.nickname_history.append(c)

    def history(self, key: str | None = None, limit: int = 500) -> list[NicknameChange]:
        items = [c for c in self._s.nickname_history if key is None or c.key == key]
        return sorted(items, key=lambda c: c.t_ms, reverse=True)[:limit]

    def has_history(self, c: NicknameChange) -> bool:
        return c in self._s.nickname_history

    def rekey(self, old: str, new: str) -> None:
        if old in self._s.nicknames:
            value = self._s.nicknames.pop(old)
            self._s.nicknames.setdefault(new, value)
        self._s.nickname_history = [
            replace(c, key=new) if c.key == old else c for c in self._s.nickname_history
        ]


class _Watches:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def list(self) -> list[Watch]:
        return list(self._s.watches.values())

    def add(self, w: Watch) -> None:
        self._s.watches[w.ip] = w

    def remove(self, ip: str) -> bool:
        return self._s.watches.pop(ip, None) is not None


class _Events:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def add(self, e: DomainEvent) -> None:
        self._s.events.append(e)

    def recent(self, limit: int = 300) -> list[DomainEvent]:
        return list(reversed(self._s.events))[:limit]


class _Inspections:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def save(self, r: InspectionReport) -> None:
        self._s.inspections[r.ip] = r

    def latest(self, ip: str) -> InspectionReport | None:
        return self._s.inspections.get(ip)


class _PluginStates:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def get(self, plugin_id: str) -> PluginState | None:
        return self._s.plugin_state.get(plugin_id)

    def save(self, s: PluginState) -> None:
        self._s.plugin_state[s.plugin_id] = s


class InMemoryUnitOfWork:
    """Works on a private copy of the shared store; ``commit`` copies it back."""

    def __init__(self, shared: _Store) -> None:
        self._shared = shared
        self._work = copy.deepcopy(shared)
        self.devices = _Devices(self._work)
        self.identity = _Identity(self._work)
        self.nicknames = _Nicknames(self._work)
        self.watches = _Watches(self._work)
        self.events = _Events(self._work)
        self.inspections = _Inspections(self._work)
        self.plugin_state = _PluginStates(self._work)
        self.committed = False

    def commit(self) -> None:
        snapshot = copy.deepcopy(self._work)
        self._shared.__dict__.update(snapshot.__dict__)
        self.committed = True

    def rollback(self) -> None:
        self._work.__dict__.update(copy.deepcopy(self._shared).__dict__)

    def __enter__(self) -> InMemoryUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self.committed:
            self.rollback()


class InMemoryUnitOfWorkFactory:
    """Every unit of work it creates shares one store."""

    def __init__(self) -> None:
        self._store = _Store()

    def __call__(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(self._store)


class FakeClock:
    def __init__(self, start_ms: int = 1_800_000_000_000) -> None:
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def advance(self, ms: int) -> None:
        self._now += ms


class RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []
        self._handlers: list[Callable[[DomainEvent], None]] = []

    def publish(self, e: DomainEvent) -> None:
        self.published.append(e)
        for handler in list(self._handlers):
            handler(e)

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        self._handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return unsubscribe


class InMemoryMetrics:
    def __init__(self) -> None:
        self._series: dict[str, list[tuple[int, float | None]]] = {}

    def append(self, series: str, t_ms: int, value: float | None) -> None:
        self._series.setdefault(series, []).append((t_ms, value))

    def series(self, name: str, limit: int = 120) -> list[tuple[int, float | None]]:
        return self._series.get(name, [])[-limit:]

    def names(self, prefix: str = "") -> list[str]:
        return sorted(n for n in self._series if n.startswith(prefix))


class FakeNetworkTools:
    def __init__(
        self,
        replies: dict[str, PingResult] | None = None,
        arp: dict[str, str] | None = None,
        local: str = "192.168.1.95",
        gateway: str | None = "192.168.1.1",
        fail: bool = False,
    ) -> None:
        self.replies = replies or {}
        self.arp = arp or {}
        self.local = local
        self.gateway = gateway
        self.fail = fail

    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
        if self.fail:
            return None
        return self.replies.get(ip)

    def arp_table(self) -> dict[str, str]:
        return {} if self.fail else dict(self.arp)

    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult:
        return TcpResult("filtered", None)

    def dns_query(self, server: str, name: str, timeout_s: float = 2.0) -> float | None:
        return None

    def local_ip(self) -> str:
        return self.local

    def default_gateway(self, local_ip: str) -> str | None:
        return self.gateway

    def hostname(self) -> str:
        return "test-host"


class FakeVendors:
    def __init__(self, table: dict[str, str] | None = None) -> None:
        self.table = table or {}

    def vendor(self, mac: str | None) -> str:
        return self.table.get(mac, "") if mac else ""
