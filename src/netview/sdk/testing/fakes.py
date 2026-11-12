"""In-memory implementations of the application ports, for tests and plugin authors."""

from __future__ import annotations

import copy
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import TracebackType
from typing import Any, cast
from unittest.mock import MagicMock

from netview.application.auth.principal import SYSTEM_PRINCIPAL, Principal
from netview.application.plugins.context import PluginUnitOfWork
from netview.application.ports.clock import Clock
from netview.application.ports.network import PingResult, TcpResult
from netview.application.ports.probes import DnsRecord, HttpProbe, NetbiosInfo, SsdpEntry
from netview.application.ports.repositories import PluginState
from netview.application.ports.snmp import Oid, SnmpError, SnmpTarget, SnmpValue
from netview.application.ports.system import TcpSocket, WifiInfo
from netview.application.queries.read_models import DeviceView
from netview.domain.device import Device, DeviceStatus
from netview.domain.events import DomainEvent, EventKind
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
    registry_ids: dict[str, int] = field(default_factory=dict)
    registry_next_id: int = 1  # monotonic: ids are never reused, like AUTOINCREMENT
    registry_folders: dict[str, str] = field(default_factory=dict)
    pending_uninstalls: list[str] = field(default_factory=list)


class _Devices:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def get(self, key: str) -> Device | None:
        return self._s.devices.get(key)

    def get_by_ip(self, ip: str) -> Device | None:
        rank = {DeviceStatus.ONLINE: 0, DeviceStatus.QUIET: 1, DeviceStatus.OFFLINE: 2}
        owners = [d for d in self._s.devices.values() if d.ip == ip]
        return min(owners, key=lambda d: (rank[d.status], -d.last_seen_ms, d.key), default=None)

    def list(self) -> list[Device]:
        return list(self._s.devices.values())

    def add(self, device: Device) -> None:
        self._s.devices[device.key] = device

    def save(self, device: Device) -> None:
        self._s.devices[device.key] = device

    def remove(self, key: str) -> None:
        self._s.devices.pop(key, None)

    def clear_new(self) -> None:
        for d in self._s.devices.values():
            d.is_new = False


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

    def all_types(self) -> dict[str, list[TypeClaim]]:
        out: dict[str, list[TypeClaim]] = defaultdict(list)
        for (k, _), t in self._s.types.items():
            out[k].append(t)
        return dict(out)

    def upsert_type(self, t: TypeClaim) -> None:
        self._s.types[(t.key, t.source)] = t

    def hints(self, key: str) -> list[Hint]:
        return [h for (k, _), hs in self._s.hints.items() if k == key for h in hs]

    def all_hints(self) -> dict[str, list[Hint]]:
        out: dict[str, list[Hint]] = defaultdict(list)
        for (k, _), hs in self._s.hints.items():
            out[k].extend(hs)
        return dict(out)

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

    def remove(self, key: str) -> None:
        for store in (self._s.claims, self._s.types, self._s.hints):
            for k in [k for k in store if k[0] == key]:
                del store[k]


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

    def last(self, kind: EventKind, ip: str) -> DomainEvent | None:
        return next((e for e in reversed(self._s.events) if e.kind is kind and e.ip == ip), None)


class _Inspections:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def save(self, r: InspectionReport) -> None:
        self._s.inspections[r.ip] = r

    def latest(self, ip: str) -> InspectionReport | None:
        return self._s.inspections.get(ip)

    def latest_times(self) -> dict[str, int]:
        return {ip: r.finished_ms for ip, r in self._s.inspections.items()}


class _PluginStates:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def get(self, plugin_id: str) -> PluginState | None:
        return self._s.plugin_state.get(plugin_id)

    def save(self, s: PluginState) -> None:
        self._s.plugin_state[s.plugin_id] = s

    def delete(self, plugin_id: str) -> None:
        self._s.plugin_state.pop(plugin_id, None)


class _PluginRegistry:
    def __init__(self, s: _Store) -> None:
        self._s = s

    def assign(self, guid: str) -> int:
        existing = self._s.registry_ids.get(guid)
        if existing is not None:
            return existing
        sid = self._s.registry_next_id
        self._s.registry_next_id += 1
        self._s.registry_ids[guid] = sid
        return sid

    def source_id(self, guid: str) -> int | None:
        return self._s.registry_ids.get(guid)

    def last_folders(self) -> dict[str, str]:
        return dict(self._s.registry_folders)

    def set_last_folder(self, guid: str, folder: str) -> None:
        self.assign(guid)
        self._s.registry_folders[guid] = folder

    def add_pending_uninstall(self, folder: str) -> None:
        if folder not in self._s.pending_uninstalls:
            self._s.pending_uninstalls.append(folder)

    def pending_uninstalls(self) -> list[str]:
        return list(self._s.pending_uninstalls)

    def clear_pending_uninstall(self, folder: str) -> None:
        if folder in self._s.pending_uninstalls:
            self._s.pending_uninstalls.remove(folder)


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
        self.plugin_registry = _PluginRegistry(self._work)
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

    def snapshot(
        self, prefixes: Sequence[str] = (), since_ms: int = 0
    ) -> dict[str, list[tuple[int, float | None]]]:
        out: dict[str, list[tuple[int, float | None]]] = {}
        for name, points in self._series.items():
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            fresh = [(t, v) for t, v in points if t > since_ms]
            if fresh:
                out[name] = fresh
        return out

    def drop(self, name: str) -> None:
        self._series.pop(name, None)


class FakeNetworkTools:
    def __init__(
        self,
        replies: dict[str, PingResult] | None = None,
        arp: dict[str, str] | None = None,
        local: str = "192.168.1.95",
        gateway: str | None = "192.168.1.1",
        fail: bool = False,
        dns: dict[str, float] | None = None,
    ) -> None:
        self.replies = replies or {}
        self.dns = dns or {}  # DNS server -> answer time in ms; a server not listed does not answer
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
        return None if self.fail else self.dns.get(server)

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


class FakeServiceProbes:
    """Canned answers for plugin tests. Anything not given comes back empty or ``None``."""

    def __init__(
        self,
        rdns: Mapping[str, str] | None = None,
        netbios: Mapping[str, NetbiosInfo] | None = None,
        mdns: Mapping[tuple[str, str], list[DnsRecord]] | None = None,
        ssdp: Sequence[SsdpEntry] = (),
        upnp: Mapping[str, dict[str, str]] | None = None,
        http: Mapping[tuple[str, int], HttpProbe] | None = None,
        banners: Mapping[tuple[str, int], bytes] | None = None,
    ) -> None:
        self.rdns = dict(rdns or {})
        self.netbios_info = dict(netbios or {})
        self.mdns = dict(mdns or {})
        self.ssdp = list(ssdp)
        self.upnp = dict(upnp or {})
        self.http = dict(http or {})
        self.banners = dict(banners or {})

    def reverse_dns(self, ip: str, timeout_s: float = 2.0) -> str:
        return self.rdns.get(ip, "")

    def netbios(self, ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None:
        return self.netbios_info.get(ip)

    def mdns_query(self, ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]:
        return list(self.mdns.get((ip, qname), []))

    def ssdp_search(
        self, target: str | None = None, timeout_s: float = 2.5, st: str = "ssdp:all"
    ) -> list[SsdpEntry]:
        return list(self.ssdp)

    def upnp_description(self, ip: str, location: str) -> dict[str, str]:
        return dict(self.upnp.get(ip, {}))

    def http_probe(self, ip: str, port: int, tls: bool, timeout_s: float = 3.0) -> HttpProbe | None:
        return self.http.get((ip, port))

    def tcp_banner(self, ip: str, port: int, timeout_s: float = 2.0) -> bytes | None:
        return self.banners.get((ip, port))


class FakeSystemInfo:
    def __init__(
        self,
        interface_bytes: tuple[int, int] | Sequence[tuple[int, int] | None] | None = None,
        wifi: WifiInfo | None = None,
        sockets: Sequence[TcpSocket] = (),
    ) -> None:
        """``interface_bytes``: one reading (always returned) or a sequence (next per call, last repeats)."""
        self._readings: list[tuple[int, int] | None]
        if interface_bytes and isinstance(interface_bytes[0], int):
            self._readings = [(interface_bytes[0], cast("int", interface_bytes[1]))]
        else:
            self._readings = list(cast("Sequence[tuple[int, int] | None]", interface_bytes or ())) or [None]
        self._wifi = wifi
        self._sockets = list(sockets)

    def interface_bytes(self) -> tuple[int, int] | None:
        return self._readings.pop(0) if len(self._readings) > 1 else self._readings[0]

    def wifi(self) -> WifiInfo | None:
        return self._wifi

    def tcp_sockets(self) -> list[TcpSocket]:
        return list(self._sockets)


class FakeSnmpClient:
    """Serves canned rows. ``fail_with`` makes every call raise; ``calls`` records each one."""

    def __init__(self, rows: Sequence[tuple[Oid, SnmpValue]]) -> None:
        self.rows: dict[Oid, SnmpValue] = dict(rows)
        self.fail_with: SnmpError | None = None
        self.calls: list[tuple[str, Oid]] = []

    @classmethod
    def from_walk_file(cls, path: Path) -> FakeSnmpClient:
        from netview.sdk.testing.snmpwalk import parse_snmpwalk

        return cls(parse_snmpwalk(path.read_text(encoding="utf-8")))

    def get(self, target: SnmpTarget, oids: Sequence[Oid]) -> dict[Oid, SnmpValue]:
        for oid in oids:
            self.calls.append(("get", oid))
        if self.fail_with is not None:
            raise self.fail_with
        return {oid: self.rows.get(oid) for oid in oids}

    def walk(self, target: SnmpTarget, prefix: Oid, max_rows: int = 10_000) -> list[tuple[Oid, SnmpValue]]:
        self.calls.append(("walk", prefix))
        if self.fail_with is not None:
            raise self.fail_with
        under = sorted((oid, v) for oid, v in self.rows.items() if oid[: len(prefix)] == prefix)
        return under[:max_rows]


class FakeCore:
    """The slice of the core facade a plugin collector uses; records what it is given."""

    def __init__(self, devices: Sequence[DeviceView] = ()) -> None:
        self.devices_list: list[DeviceView] = list(devices)
        self.claims: list[NameClaim | TypeClaim | Hint] = []
        self.events: list[tuple[EventKind, str, str | None]] = []

    def devices(self) -> list[DeviceView]:
        return list(self.devices_list)

    def claim(self, items: Sequence[NameClaim | TypeClaim | Hint]) -> None:
        self.claims.extend(items)

    def add_event(self, kind: EventKind, text: str, ip: str | None = None) -> None:
        self.events.append((kind, text, ip))


class _NullUnitOfWork:
    def __init__(self) -> None:
        self.session: Any = MagicMock()

    def commit(self) -> None:
        return None

    def __enter__(self) -> _NullUnitOfWork:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakePluginContext:
    """A ``PluginContext`` made of fakes. ``clock`` is a ``FakeClock`` unless one is passed."""

    def __init__(
        self,
        settings: Any,
        *,
        snmp: Any,
        core: Any,
        uow_factory: Callable[[], PluginUnitOfWork] | None = None,
        clock: Clock | None = None,
        guid: str = "00000000-0000-4000-8000-000000000000",
        source_id: int = 1,
        display_name: str = "Fake",
    ) -> None:
        self.guid = guid
        self.source_id = source_id
        self.display_name = display_name
        self.settings = settings
        self.log = logging.getLogger(f"netview.plugin.p{source_id}")
        self.clock: Any = clock if clock is not None else FakeClock()
        self.net = FakeNetworkTools()
        self.vendors = FakeVendors()
        self.metrics = InMemoryMetrics()
        self.snmp = snmp
        self.core = core
        self._uow_factory: Callable[[], PluginUnitOfWork] = uow_factory or _NullUnitOfWork

    def unit_of_work(self) -> PluginUnitOfWork:
        return self._uow_factory()

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        return lambda: None

    def require(self, permission_id: str) -> Any:
        """A dependency that lets everyone through."""
        from fastapi import Depends

        def allow() -> None:
            return None

        return Depends(allow)

    def principal(self) -> Principal:
        return SYSTEM_PRINCIPAL

    def audit(
        self, action: str, target: str | None = None, ok: bool = True, detail: str | None = None
    ) -> None:
        return None
