"""Joins the collector, analysis, storage and ``ctx.core``: one method per job, plus the read models."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any, Literal, cast

from netview.sdk import (
    DeviceView,
    EventKind,
    Hint,
    NameClaim,
    PluginContext,
    SnmpAuthError,
    SnmpError,
    SnmpTarget,
    SnmpTimeout,
    TypeClaim,
)

from . import mibs
from .analysis import (
    REACHABLE_TEXT,
    UNREACHABLE_TEXT,
    Attachment,
    attribute,
    compute_rates,
    detect_uplinks,
    diff,
    merge_snapshot,
    rebooted,
)
from .collector import Collector
from .model import PollGroup, Port, PortCounters, PortRates, Snapshot
from .settings import Gsm7248Settings
from .storage import SwitchStore

SOURCE = "GSM7248"
SWITCH_ID = "gsm7248"
NAME_RANK = 8
MAX_BACKOFF_S = 300
MASK = "********"
# the cheap scalar GET: only this group decides whether the switch is reachable
REACHABILITY_GROUP = "status"
_SWITCH_TYPE_REASON = "SNMP sysObjectID 1.3.6.1.4.1.4526"
_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000

Resolution = Literal["raw", "5m"]


class Gsm7248Service:
    def __init__(
        self,
        ctx: PluginContext,
        store_factory: Callable[[str], SwitchStore],
        collector: Collector,
    ) -> None:
        self._ctx = ctx
        self._store = store_factory(SWITCH_ID)
        self._collector = collector
        # one lock around each whole poll: the scheduler runs these jobs on a thread pool
        self._lock = threading.Lock()
        self._current: Snapshot | None = self._load_snapshot()
        self._uplinks: frozenset[int] = frozenset()
        self._last_counters: dict[int, PortCounters] = {}
        self._rates: dict[int, PortRates] = {}
        self._drop_rates = False
        self._reachable: bool | None = None
        self._last_poll_ms: int | None = None
        self._errors: dict[str, str] = {}  # group -> its latest scrubbed error, newest last
        self._failures: dict[str, int] = {}
        self._next_allowed: dict[str, int] = {}
        self._claimed: dict[tuple[str, str], tuple[str, ...]] = {}
        self._refresh_uplinks()

    # ---- helpers -------------------------------------------------------------------------------

    @property
    def settings(self) -> Gsm7248Settings:
        settings: Gsm7248Settings = self._ctx.settings
        return settings

    def _load_snapshot(self) -> Snapshot | None:
        try:
            return self._store.load_snapshot()
        except Exception:  # a missing or unreadable snapshot only means the next polls are baselines
            self._ctx.log.warning("could not load the stored GSM7248 snapshot", exc_info=True)
            return None

    def _scrub(self, text: str) -> str:
        s = self.settings
        for secret in (s.community, s.v3_auth_key, s.v3_priv_key):
            value = secret.get_secret_value() if secret is not None else ""
            if value:
                text = text.replace(value, MASK)
        return text

    def _describe(self, exc: BaseException) -> str:
        text = str(exc)
        return self._scrub(f"{type(exc).__name__}: {text}" if text else type(exc).__name__)

    def _detect_uplinks(self, snapshot: Snapshot, devices: list[DeviceView]) -> frozenset[int]:
        net = self._ctx.net
        gateway_ip = net.default_gateway(net.local_ip())
        gateway_mac = next(
            (d.mac.lower() for d in devices if gateway_ip is not None and d.ip == gateway_ip and d.mac),
            None,
        )
        s = self.settings
        return detect_uplinks(snapshot, gateway_mac, frozenset(s.uplink_ports), s.uplink_mac_threshold)

    def _refresh_uplinks(self) -> None:
        if self._current is None:
            return
        try:
            self._uplinks = self._detect_uplinks(self._current, self._ctx.core.devices())
        except Exception:
            self._ctx.log.debug("could not work out the uplink ports yet", exc_info=True)

    def settings_changed(self) -> None:
        """New settings: try the switch again at once, and re-evaluate the uplinks."""
        self._failures.clear()
        self._next_allowed.clear()
        self._errors.clear()
        self._refresh_uplinks()

    # ---- running polls -------------------------------------------------------------------------

    def _run(self, group: str, interval_s: int, fn: Callable[[SnmpTarget, int], bool], force: bool) -> bool:
        """One poll, with the lock already held. False when the switch did not answer."""
        target = self.settings.target()
        if target is None:
            return True
        now = self._ctx.clock.now_ms()
        if not force and now < self._next_allowed.get(group, 0):
            return True
        try:
            polled = fn(target, now)
        except SnmpError as exc:
            self._failed(group, interval_s, exc, now)
            return False
        if polled:
            self._succeeded(group, now)
        return True

    def _locked(self, group: str, interval_s: int, fn: Callable[[SnmpTarget, int], bool]) -> None:
        with self._lock:
            self._run(group, interval_s, fn, force=False)

    def poll_counters(self) -> None:
        self._locked("counters", self.settings.counters_interval_s, self._counters)

    def poll_status(self) -> None:
        self._locked("status", self.settings.status_interval_s, self._status)

    def poll_bridge(self) -> None:
        self._locked("bridge", self.settings.bridge_interval_s, self._bridge)

    def poll_topology(self) -> None:
        self._locked("topology", self.settings.topology_interval_s, self._topology)

    def _run_all(self) -> None:
        s = self.settings
        steps: list[tuple[str, int, Callable[[SnmpTarget, int], bool]]] = [
            ("status", s.status_interval_s, self._status),
            ("topology", s.topology_interval_s, self._topology),
            ("bridge", s.bridge_interval_s, self._bridge),
            ("counters", s.counters_interval_s, self._counters),
        ]
        for group, interval_s, fn in steps:
            if not self._run(group, interval_s, fn, force=True):
                break  # the switch is not answering: do not wait for three more timeouts

    def poll_all(self) -> bool:
        """Every group now, ignoring the backoff. False when a poll is already running."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._run_all()
        finally:
            self._lock.release()
        return True

    def start_poll_all(self) -> bool:
        """Like ``poll_all`` on a background thread; False (decided now) when a poll is running."""
        if not self._lock.acquire(blocking=False):
            return False

        def work() -> None:
            try:
                self._run_all()
            except Exception:
                self._ctx.log.exception("GSM7248 poll failed")
            finally:
                self._lock.release()

        try:
            threading.Thread(target=work, name="gsm7248-poll-all", daemon=True).start()
        except BaseException:
            self._lock.release()
            raise
        return True

    def prune(self) -> None:
        """Roll up and delete old samples. Storage only, so it does not wait for (or block) a poll."""
        s = self.settings
        self._store.rollup_and_prune(
            self._ctx.clock.now_ms(), s.raw_retention_h * _HOUR_MS, s.rollup_retention_d * _DAY_MS
        )

    def test_connection(self, target: SnmpTarget) -> dict[str, str]:
        try:
            values = self._ctx.snmp.get(target, [mibs.SYS_DESCR])
        except SnmpError as exc:
            return {"ok": "false", "error": self._describe(exc)}
        descr = values.get(mibs.SYS_DESCR)
        text = descr.decode("utf-8", "replace") if isinstance(descr, bytes) else str(descr or "")
        return {"ok": "true", "sys_descr": text}

    # ---- reachability --------------------------------------------------------------------------

    @property
    def _last_error(self) -> str | None:
        """The reachability group's error first, else the newest error of any group."""
        if REACHABILITY_GROUP in self._errors:
            return self._errors[REACHABILITY_GROUP]
        return next(reversed(self._errors.values()), None)

    def _failed(self, group: str, interval_s: int, exc: SnmpError, now: int) -> None:
        """Back off this group only. Only the reachability group can declare the switch unreachable."""
        message = self._describe(exc)
        self._errors.pop(group, None)
        self._errors[group] = message
        self._ctx.log.warning("GSM7248 %s poll failed: %s", group, message)
        failures = min(self._failures.get(group, 0) + 1, 10)
        self._failures[group] = failures
        delay_s = min(MAX_BACKOFF_S, interval_s * 2**failures)
        self._next_allowed[group] = now + int(delay_s * 1000)
        if (
            group == REACHABILITY_GROUP
            and isinstance(exc, SnmpTimeout | SnmpAuthError)
            and self._reachable is not False
        ):
            self._reachable = False
            self._ctx.core.add_event(EventKind.PLUGIN, UNREACHABLE_TEXT, None)

    def _succeeded(self, group: str, now: int) -> None:
        """Clear this group's error and backoff. A reachability-group success after an outage
        also lifts every other group's backoff, so the data refreshes at once."""
        self._errors.pop(group, None)
        self._failures.pop(group, None)
        self._next_allowed.pop(group, None)
        self._last_poll_ms = now
        if group != REACHABILITY_GROUP:
            return
        was = self._reachable
        self._reachable = True
        if was is False:
            self._failures.clear()
            self._next_allowed.clear()
            self._ctx.core.add_event(EventKind.PLUGIN, REACHABLE_TEXT, None)

    # ---- the poll groups -----------------------------------------------------------------------

    def _counters(self, target: SnmpTarget, now: int) -> bool:
        snapshot = self._current
        if snapshot is None:
            return False
        linked = [p.if_index for p in snapshot.ports if p.oper_up]
        if not linked:
            return False
        counters = self._collector.counters(target, now, linked)
        drop, self._drop_rates = self._drop_rates, False
        speeds = {p.if_index: p.speed_mbps for p in snapshot.ports}
        rates: dict[int, PortRates] = {}
        if not drop:
            for cur in counters:
                prev = self._last_counters.get(cur.if_index)
                rate = compute_rates(prev, cur, speeds.get(cur.if_index)) if prev is not None else None
                if rate is not None:
                    rates[cur.if_index] = rate
        self._last_counters = {c.if_index: c for c in counters}
        self._rates = rates
        if rates:
            self._store.add_samples(list(rates.values()), self._last_counters)
        return True

    def _status(self, target: SnmpTarget, now: int) -> bool:
        part = self._collector.status(target, now)
        previous = self._current.info if self._current is not None else None
        if part.info is not None and previous is not None and rebooted(previous, part.info):
            self._drop_rates = True
        self._apply(part, "status")
        return True

    def _bridge(self, target: SnmpTarget, now: int) -> bool:
        self._apply(self._collector.bridge(target, now), "bridge")
        return True

    def _topology(self, target: SnmpTarget, now: int) -> bool:
        self._apply(self._collector.topology(target, now), "topology")
        return True

    def _apply(self, part: Snapshot, group: PollGroup) -> None:
        ctx = self._ctx
        previous = self._current
        merged = merge_snapshot(previous, part)
        devices = ctx.core.devices()
        by_mac = {d.mac.lower(): d for d in devices if d.mac}
        uplinks = self._detect_uplinks(merged, devices)

        changes = diff(
            previous,
            merged,
            known_macs=frozenset(by_mac),
            seen_macs=self._store.seen_macs(),
            uplinks=uplinks,
            low_memory_kb=self.settings.low_memory_kb,
        )
        for change in changes:
            owner = by_mac.get(change.mac) if change.mac else None
            ctx.core.add_event(EventKind.PLUGIN, change.text, owner.ip if owner else None)

        self._store.save_snapshot(merged)
        self._current = merged
        self._uplinks = uplinks

        if group in ("bridge", "topology"):
            self._claim_attachments(merged, uplinks, {mac: d.key for mac, d in by_mac.items()})
        if group == "status" and merged.info is not None:
            self._claim_switch(merged, devices)

    def _claim_attachments(
        self, snapshot: Snapshot, uplinks: frozenset[int], keys_by_mac: Mapping[str, str]
    ) -> None:
        attachments = attribute(snapshot, uplinks, keys_by_mac)
        self._store.touch_macs(attachments, snapshot.t_ms)
        texts: dict[str, set[str]] = {}
        for a in attachments:
            if a.device_key is None:
                continue
            text = (
                f"via GSM7248 uplink {a.port_name}"
                if a.via_uplink
                else f"on GSM7248 port {a.port_name} (VLAN {a.vlan})"
            )
            texts.setdefault(a.device_key, set()).add(text)
        items: list[Hint] = []
        sent: dict[tuple[str, str], tuple[str, ...]] = {}
        for key, found in texts.items():
            ordered = tuple(sorted(found))
            if self._claimed.get(("port", key)) == ordered:
                continue
            items.extend(Hint(key, text, SOURCE) for text in ordered)
            sent[("port", key)] = ordered
        if items:
            self._ctx.core.claim(items)
            self._claimed.update(sent)

    def _claim_switch(self, snapshot: Snapshot, devices: list[DeviceView]) -> None:
        info = snapshot.info
        if info is None:
            return
        host = self.settings.host
        mac = info.mac.lower() if info.mac else None
        device = next((d for d in devices if mac is not None and d.mac and d.mac.lower() == mac), None)
        device = device or next((d for d in devices if d.ip == host), None)
        if device is None:
            return
        name = info.sys_name or SOURCE
        inventory = snapshot.inventory
        hint = (
            f"NETGEAR {inventory.model or 'GSM7248'} firmware {inventory.firmware or '?'}"
            if inventory is not None
            else ""
        )
        signature = (name, hint)
        if self._claimed.get(("switch", device.key)) == signature:
            return
        items: list[NameClaim | TypeClaim | Hint] = [
            NameClaim(device.key, name, SOURCE, NAME_RANK, self._ctx.clock.now_ms()),
            TypeClaim(device.key, "switch", _SWITCH_TYPE_REASON, SOURCE),
        ]
        if hint:
            items.append(Hint(device.key, hint, SOURCE))
        self._ctx.core.claim(items)
        self._claimed[("switch", device.key)] = signature

    # ---- read models ---------------------------------------------------------------------------

    def _vendor(self, mac: str, device: DeviceView | None) -> str:
        return (device.vendor if device is not None and device.vendor else "") or self._ctx.vendors.vendor(
            mac
        )

    def _attachments(self, snapshot: Snapshot, devices: list[DeviceView]) -> list[Attachment]:
        keys = {d.mac.lower(): d.key for d in devices if d.mac}
        return attribute(snapshot, self._uplinks, keys)

    def _port_entries(self, snapshot: Snapshot, devices: list[DeviceView]) -> list[dict[str, Any]]:
        by_mac = {d.mac.lower(): d for d in devices if d.mac}
        on_port: dict[int, list[dict[str, Any]]] = {}
        for a in self._attachments(snapshot, devices):
            owner = by_mac.get(a.mac)
            on_port.setdefault(a.if_index, []).append(
                {
                    "mac": a.mac,
                    "vlan": a.vlan,
                    "device_key": a.device_key,
                    "display_name": owner.display_name if owner else None,
                    "ip": owner.ip if owner else None,
                    "vendor": self._vendor(a.mac, owner),
                }
            )
        membership: dict[int, dict[str, list[int]]] = {}
        for vlan in sorted(snapshot.vlans, key=lambda v: v.vid):
            for if_index in vlan.egress:
                kind = "untagged" if if_index in vlan.untagged else "tagged"
                membership.setdefault(if_index, {"untagged": [], "tagged": []})[kind].append(vlan.vid)
        stp = {s.if_index: s.state for s in snapshot.stp}
        lag_of = {m: g.name for g in snapshot.lags for m in g.members}
        entries: list[dict[str, Any]] = []
        for p in snapshot.ports:
            rates = self._rates.get(p.if_index)
            entries.append(
                {
                    "if_index": p.if_index,
                    "name": p.name,
                    "alias": p.alias,
                    "kind": p.kind,
                    "admin_up": p.admin_up,
                    "oper_up": p.oper_up,
                    "speed_mbps": p.speed_mbps,
                    "duplex": p.duplex,
                    "pvid": snapshot.pvid(p.if_index),
                    "vlans": membership.get(p.if_index, {"untagged": [], "tagged": []}),
                    "stp_state": stp.get(p.if_index),
                    "lag": lag_of.get(p.if_index),
                    "uplink": p.if_index in self._uplinks,
                    "rates": asdict(rates) if rates is not None else None,
                    "devices": on_port.get(p.if_index, []),
                }
            )
        return entries

    def summary(self) -> dict[str, Any]:
        snapshot = self._current
        info = snapshot.info if snapshot else None
        inventory = snapshot.inventory if snapshot else None
        health = snapshot.health if snapshot else None
        ethernet: list[Port] = [p for p in snapshot.ports if p.kind == "ethernet"] if snapshot else []
        rates = [self._rates[p.if_index] for p in ethernet if p.if_index in self._rates]
        return {
            "configured": self.settings.target() is not None,
            "reachable": self._reachable,
            "last_poll_ms": self._last_poll_ms,
            "last_error": self._last_error,
            "switch": None
            if info is None
            else {
                "name": info.sys_name,
                "model": inventory.model if inventory else None,
                "firmware": inventory.firmware if inventory else None,
                "serial": inventory.serial if inventory else None,
                "mac": info.mac,
                "uptime_s": info.uptime_cs // 100,
            },
            "health": {
                "cpu_percent": health.cpu_percent if health else None,
                "mem_free_kb": health.mem_free_kb if health else None,
                "mem_total_kb": health.mem_total_kb if health else None,
            },
            "ports": {
                "total": len(ethernet),
                "up": sum(1 for p in ethernet if p.oper_up),
                "uplinks": sum(1 for p in ethernet if p.if_index in self._uplinks),
            },
            "throughput_bps": {
                "in": sum(r.in_bps for r in rates),
                "out": sum(r.out_bps for r in rates),
            },
        }

    def ports(self) -> list[dict[str, Any]]:
        snapshot = self._current
        if snapshot is None:
            return []
        return self._port_entries(snapshot, self._ctx.core.devices())

    def has_port(self, name: str) -> bool:
        snapshot = self._current
        return snapshot is not None and snapshot.port_by_name(name) is not None

    def port(self, name: str) -> dict[str, Any] | None:
        snapshot = self._current
        if snapshot is None:
            return None
        entry = next(
            (e for e in self._port_entries(snapshot, self._ctx.core.devices()) if e["name"] == name), None
        )
        if entry is None:
            return None
        entry["mac_history"] = self._store.mac_history(if_index=entry["if_index"])
        return entry

    def samples(
        self, name: str, from_ms: int | None, to_ms: int | None, step: str = "raw"
    ) -> list[dict[str, Any]]:
        snapshot = self._current
        port = snapshot.port_by_name(name) if snapshot else None
        if port is None:
            return []
        end = to_ms if to_ms is not None else self._ctx.clock.now_ms()
        start = from_ms if from_ms is not None else end - (_HOUR_MS if step == "raw" else _DAY_MS)
        rows = self._store.samples(port.if_index, start, end, cast("Resolution", step))
        return [asdict(r) for r in rows]

    def macs(self) -> list[dict[str, Any]]:
        snapshot = self._current
        if snapshot is None:
            return []
        devices = self._ctx.core.devices()
        by_mac = {d.mac.lower(): d for d in devices if d.mac}
        names = {p.if_index: p.name for p in snapshot.ports}
        return [
            {
                "mac": m.mac,
                "vlan": m.vlan,
                "if_index": m.if_index,
                "port": names.get(m.if_index) if m.if_index is not None else None,
                "status": m.status,
                "via_uplink": m.if_index in self._uplinks if m.if_index is not None else False,
                "device_key": by_mac[m.mac].key if m.mac in by_mac else None,
                "display_name": by_mac[m.mac].display_name if m.mac in by_mac else None,
                "ip": by_mac[m.mac].ip if m.mac in by_mac else None,
                "vendor": self._vendor(m.mac, by_mac.get(m.mac)),
            }
            for m in snapshot.macs
        ]

    def vlans(self) -> list[dict[str, Any]]:
        snapshot = self._current
        if snapshot is None:
            return []
        names = {p.if_index: p.name for p in snapshot.ports}

        def named(indexes: frozenset[int]) -> list[str]:
            return [names.get(i, f"if{i}") for i in sorted(indexes)]

        return [
            {
                "vid": v.vid,
                "name": v.name,
                "untagged": named(v.untagged),
                "tagged": named(v.egress - v.untagged),
            }
            for v in sorted(snapshot.vlans, key=lambda v: v.vid)
        ]
