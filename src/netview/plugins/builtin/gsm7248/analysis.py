"""Pure rules over GSM7248 snapshots: rates, uplinks, attribution, change detection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from .model import GROUP_FIELDS, MacEntry, PortCounters, PortRates, Snapshot, SwitchInfo

_WRAP = 2**32
_SPIKE_FACTOR = 1.1
_UNKNOWN_SPEED_MAX_WRAPPED_DELTA = 2**31


def compute_rates(prev: PortCounters, cur: PortCounters, speed_mbps: int | None) -> PortRates | None:
    """Per-second rates between two counter samples, or None when they cannot be trusted."""
    if cur.t_ms <= prev.t_ms or prev.hc != cur.hc:
        return None
    seconds = (cur.t_ms - prev.t_ms) / 1000
    limit_bps = speed_mbps * 1e6 * _SPIKE_FACTOR if speed_mbps else None

    def delta(before: int, after: int, *, octets: bool) -> int | None:
        diff = after - before
        if diff >= 0:
            return diff
        if cur.hc:
            return None  # an HC counter never wraps in practice: this is a reset
        if not octets:
            return None  # errors/discards cannot wrap within one poll: this is a reset
        diff += _WRAP
        if limit_bps is not None:
            if diff * 8 / seconds > limit_bps:
                return None
        elif diff > _UNKNOWN_SPEED_MAX_WRAPPED_DELTA:
            return None
        return diff

    d_in = delta(prev.in_octets, cur.in_octets, octets=True)
    d_out = delta(prev.out_octets, cur.out_octets, octets=True)
    d_in_err = delta(prev.in_errors, cur.in_errors, octets=False)
    d_out_err = delta(prev.out_errors, cur.out_errors, octets=False)
    d_in_disc = delta(prev.in_discards, cur.in_discards, octets=False)
    d_out_disc = delta(prev.out_discards, cur.out_discards, octets=False)
    if d_in is None or d_out is None or d_in_err is None or d_out_err is None:
        return None
    if d_in_disc is None or d_out_disc is None:
        return None

    in_bps = d_in * 8 / seconds
    out_bps = d_out * 8 / seconds
    util = max(in_bps, out_bps) / (speed_mbps * 1e6) * 100 if speed_mbps else None
    return PortRates(
        if_index=cur.if_index,
        t_ms=cur.t_ms,
        in_bps=in_bps,
        out_bps=out_bps,
        in_err_ps=d_in_err / seconds,
        out_err_ps=d_out_err / seconds,
        in_disc_ps=d_in_disc / seconds,
        out_disc_ps=d_out_disc / seconds,
        util_percent=util,
    )


def rebooted(prev: SwitchInfo | None, cur: SwitchInfo) -> bool:
    return prev is not None and cur.uptime_cs < prev.uptime_cs


def _learned(snapshot: Snapshot) -> list[tuple[MacEntry, int]]:
    return [(m, m.if_index) for m in snapshot.macs if m.status == "learned" and m.if_index is not None]


def detect_uplinks(
    snapshot: Snapshot,
    gateway_mac: str | None,
    configured: frozenset[str],
    mac_threshold: int,
) -> frozenset[int]:
    """ifIndex values of ports that lead to the rest of the network."""
    uplinks = {p.if_index for p in snapshot.ports if p.name in configured}
    macs_by_port: dict[int, set[str]] = defaultdict(set)
    for entry, if_index in _learned(snapshot):
        macs_by_port[if_index].add(entry.mac)
    gateway = gateway_mac.lower() if gateway_mac else None
    for if_index, macs in macs_by_port.items():
        if len(macs) > mac_threshold or (gateway is not None and gateway in macs):
            uplinks.add(if_index)
    return frozenset(uplinks)


@dataclass(frozen=True, slots=True)
class Attachment:
    mac: str
    if_index: int
    port_name: str
    vlan: int
    via_uplink: bool
    device_key: str | None


def _port_name(snapshot: Snapshot, if_index: int) -> str:
    port = snapshot.port(if_index)
    return port.name if port else f"if{if_index}"


def attribute(
    snapshot: Snapshot,
    uplinks: frozenset[int],
    device_keys_by_mac: Mapping[str, str],
) -> list[Attachment]:
    """Learned MACs with their port, VLAN and (when known) device. Skips self and mgmt entries."""
    return [
        Attachment(
            mac=entry.mac,
            if_index=if_index,
            port_name=_port_name(snapshot, if_index),
            vlan=entry.vlan,
            via_uplink=if_index in uplinks,
            device_key=device_keys_by_mac.get(entry.mac),
        )
        for entry, if_index in _learned(snapshot)
    ]


def single_device_ports(attachments: Sequence[Attachment]) -> dict[int, str]:
    """ifIndex -> device_key for non-uplink ports that carry exactly one MAC, and it is known."""
    macs: dict[int, set[str]] = defaultdict(set)
    keys: dict[int, str | None] = {}
    for a in attachments:
        if a.via_uplink:
            continue
        macs[a.if_index].add(a.mac)
        keys[a.if_index] = a.device_key
    return {i: k for i, m in macs.items() if len(m) == 1 and (k := keys[i]) is not None}


class ChangeKind(StrEnum):
    LINK_UP = "link_up"
    LINK_DOWN = "link_down"
    ADMIN_CHANGED = "admin_changed"
    MAC_NEW = "mac_new"
    MAC_MOVED = "mac_moved"
    MAC_GONE = "mac_gone"
    STP_CHANGED = "stp_changed"
    REBOOTED = "rebooted"
    LOW_MEMORY = "low_memory"
    UNREACHABLE = "unreachable"
    REACHABLE = "reachable"


# Produced by the service, not by diff(); the texts live here so they stay in one place.
UNREACHABLE_TEXT = "GSM7248 is not answering SNMP"
REACHABLE_TEXT = "GSM7248 is answering SNMP again"


@dataclass(frozen=True, slots=True)
class Change:
    kind: ChangeKind
    text: str
    if_index: int | None = None
    mac: str | None = None


def diff(
    prev: Snapshot | None,
    cur: Snapshot,
    *,
    known_macs: frozenset[str],
    seen_macs: frozenset[str],
    uplinks: frozenset[int],
    low_memory_kb: int,
) -> list[Change]:
    """Changes from ``prev`` to ``cur``. A group is compared only when both snapshots hold it."""
    if prev is None:
        return []
    changes: list[Change] = []
    both = prev.groups & cur.groups

    if "status" in both:
        changes.extend(_port_changes(prev, cur))
        if prev.info is not None and cur.info is not None and rebooted(prev.info, cur.info):
            changes.append(Change(ChangeKind.REBOOTED, "GSM7248 restarted"))
        if prev.health is not None and cur.health is not None:
            before, after = prev.health.mem_free_kb, cur.health.mem_free_kb
            if before is not None and after is not None and before >= low_memory_kb > after:
                changes.append(Change(ChangeKind.LOW_MEMORY, f"GSM7248 memory low: {after} KB free"))
    if "bridge" in both:
        changes.extend(_mac_changes(prev, cur, known_macs, seen_macs, uplinks))
    if "topology" in both:
        changes.extend(_stp_changes(prev, cur))
    return changes


def _port_changes(prev: Snapshot, cur: Snapshot) -> list[Change]:
    changes: list[Change] = []
    for port in cur.ports:
        old = prev.port(port.if_index)
        if old is None:
            continue
        if old.oper_up != port.oper_up:
            if port.oper_up:
                speed = f" at {port.speed_mbps} Mb/s" if port.speed_mbps is not None else ""
                text = f"GSM7248 port {port.name} link up{speed}"
                changes.append(Change(ChangeKind.LINK_UP, text, if_index=port.if_index))
            else:
                text = f"GSM7248 port {port.name} link down"
                changes.append(Change(ChangeKind.LINK_DOWN, text, if_index=port.if_index))
        if old.admin_up != port.admin_up:
            state = "enabled" if port.admin_up else "disabled"
            text = f"GSM7248 port {port.name} {state}"
            changes.append(Change(ChangeKind.ADMIN_CHANGED, text, if_index=port.if_index))
    return changes


def _location_by_mac_vlan(snapshot: Snapshot) -> dict[tuple[str, int], int]:
    located: dict[tuple[str, int], int] = {}
    for entry, if_index in _learned(snapshot):
        located.setdefault((entry.mac, entry.vlan), if_index)
    return located


def _mac_changes(
    prev: Snapshot,
    cur: Snapshot,
    known_macs: frozenset[str],
    seen_macs: frozenset[str],
    uplinks: frozenset[int],
) -> list[Change]:
    changes: list[Change] = []
    prev_at = _location_by_mac_vlan(prev)
    cur_at = _location_by_mac_vlan(cur)

    announced: set[str] = set()
    for (mac, vlan), if_index in cur_at.items():
        if mac not in seen_macs and mac not in announced and if_index not in uplinks:
            announced.add(mac)
            text = f"{mac} appeared on GSM7248 port {_port_name(cur, if_index)} (VLAN {vlan})"
            changes.append(Change(ChangeKind.MAC_NEW, text, if_index=if_index, mac=mac))
        old_index = prev_at.get((mac, vlan))
        if (
            old_index is not None
            and old_index != if_index
            and old_index not in uplinks
            and if_index not in uplinks
        ):
            text = (
                f"{mac} moved from GSM7248 port {_port_name(prev, old_index)} to {_port_name(cur, if_index)}"
            )
            changes.append(Change(ChangeKind.MAC_MOVED, text, if_index=if_index, mac=mac))

    present = {mac for mac, _ in cur_at}
    gone: set[str] = set()
    for (mac, _vlan), old_index in prev_at.items():
        if mac in known_macs and mac not in present and mac not in gone:
            gone.add(mac)
            text = f"{mac} left GSM7248 port {_port_name(prev, old_index)}"
            changes.append(Change(ChangeKind.MAC_GONE, text, if_index=old_index, mac=mac))
    return changes


def _stp_changes(prev: Snapshot, cur: Snapshot) -> list[Change]:
    old_states = {s.if_index: s.state for s in prev.stp}
    changes: list[Change] = []
    for s in cur.stp:
        old = old_states.get(s.if_index)
        if old is not None and old != s.state:
            text = f"GSM7248 port {_port_name(cur, s.if_index)} spanning tree {old} → {s.state}"
            changes.append(Change(ChangeKind.STP_CHANGED, text, if_index=s.if_index))
    return changes


def merge_snapshot(base: Snapshot | None, part: Snapshot) -> Snapshot:
    """Overlay the groups polled in ``part`` onto ``base``, keeping every other field."""
    if base is None:
        return part
    fields: dict[str, Any] = {}
    for group in part.groups:
        for name in GROUP_FIELDS[group]:
            fields[name] = getattr(part, name)
    return replace(base, t_ms=part.t_ms, groups=base.groups | part.groups, **fields)
