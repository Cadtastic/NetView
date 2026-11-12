"""Rates, counter-reset detection, CRC alerts and change summaries for the GS105E.

Pure functions over the model types. Standard library only.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from .model import GROUP_FIELDS, PortCounters, PortRates, Snapshot

PREFIX = "GS105E: "
UNREACHABLE_TEXT = "GS105E: the switch is not answering"
REACHABLE_TEXT = "GS105E: the switch is answering again"
LOGIN_FAILED_TEXT = (
    "GS105E: login failed; polling stopped until the password or address changes "
    "or Test connection is pressed"
)
PAUSED_ANOTHER_LOGIN_TEXT = "GS105E: paused, another login keeps ending netview's session"
COUNTERS_RESET_TEXT = "GS105E: counters reset (switch rebooted or statistics cleared)"

CRC_ALERT_INTERVAL_MS = 3_600_000


class ChangeKind(StrEnum):
    LINK_UP = "link_up"
    LINK_DOWN = "link_down"
    SPEED = "speed"
    CRC = "crc"
    FIRMWARE = "firmware"
    CONFIG = "config"
    ACCESS_LIST = "access_list"


@dataclass(frozen=True, slots=True)
class Change:
    kind: ChangeKind
    text: str
    port: int | None = None


def compute_rates(prev: PortCounters, cur: PortCounters, link_mbps: int | None) -> PortRates | None:
    """Rates between two counter reads, or None when time or a counter did not move forward."""
    if cur.t_ms <= prev.t_ms:
        return None
    if cur.rx_bytes < prev.rx_bytes or cur.tx_bytes < prev.tx_bytes or cur.crc_errors < prev.crc_errors:
        return None
    seconds = (cur.t_ms - prev.t_ms) / 1000
    in_bps = (cur.rx_bytes - prev.rx_bytes) * 8 / seconds
    out_bps = (cur.tx_bytes - prev.tx_bytes) * 8 / seconds
    util = None if not link_mbps else max(in_bps, out_bps) / (link_mbps * 1e6) * 100
    return PortRates(cur.port, cur.t_ms, in_bps, out_bps, cur.crc_errors - prev.crc_errors, util)


def counters_reset(prev: Mapping[int, PortCounters], cur: Sequence[PortCounters]) -> bool:
    """True when some port had traffic before and every such port now shows less."""
    busy = {p: c.rx_bytes + c.tx_bytes for p, c in prev.items() if c.rx_bytes + c.tx_bytes > 0}
    if not busy:
        return False
    now = {c.port: c.rx_bytes + c.tx_bytes for c in cur}
    return all(p in now and now[p] < before for p, before in busy.items())


def crc_alerts(
    rates: Sequence[PortRates],
    threshold: int,
    last_alert_ms: MutableMapping[int, int],
    now_ms: int,
) -> list[Change]:
    """One alert per port above ``threshold``, at most once an hour per port."""
    changes: list[Change] = []
    for r in rates:
        if r.crc_delta <= threshold:
            continue
        last = last_alert_ms.get(r.port)
        if last is not None and now_ms - last <= CRC_ALERT_INTERVAL_MS:
            continue
        last_alert_ms[r.port] = now_ms
        text = f"{PREFIX}port {r.port} CRC errors rising ({r.crc_delta} in the last poll)"
        changes.append(Change(ChangeKind.CRC, text, port=r.port))
    return changes


def ip_allowed(ip: str, access_list: Sequence[tuple[str, str]]) -> bool:
    """An empty Access Control list allows every address."""
    if not access_list:
        return True
    addr = ipaddress.ip_address(ip)
    for net_ip, mask in access_list:
        try:
            if addr in ipaddress.ip_network(f"{net_ip}/{mask}", strict=False):
                return True
        except ValueError:
            continue
    return False


# --- diff -------------------------------------------------------------------------------------


def _on_off(value: bool) -> str:
    return "on" if value else "off"


def _none(value: object) -> str:
    return "none" if value is None or value == "" else str(value)


def _kbps(value: int | None) -> str:
    return "none" if value is None else f"{value} kbps"


def _port_or_none(value: int | None) -> str:
    return "none" if value is None else f"port {value}"


def _ports(value: tuple[int, ...]) -> str:
    return ", ".join(str(p) for p in value) if value else "none"


# A setting: (label, group, attribute, formatter). Booleans read "turned on/off"; other values
# read "old → new" through the formatter. A setting is skipped when its group is missing.
_Setting = tuple[str, str, str, Callable[[Any], str] | None]

_CONFIG_SETTINGS: tuple[_Setting, ...] = (
    ("switch name", "info", "name", _none),
    ("DHCP", "info", "dhcp", None),
    ("IP address", "info", "ip", None),
    ("subnet mask", "info", "mask", None),
    ("gateway", "info", "gateway", None),
    ("VLAN mode", "vlans", "mode", None),
    ("IGMP snooping", "igmp", "enabled", None),
    ("IGMP snooping VLAN", "igmp", "vlan", _none),
    ("IGMP v3 header validation", "igmp", "validate_v3_header", None),
    ("IGMP unknown multicast blocking", "igmp", "block_unknown", None),
    ("IGMP router port", "igmp", "router_port", _none),
    ("QoS mode", "qos", "mode", None),
    ("storm control", "qos", "storm_control", None),
    ("mirroring", "mirror", "enabled", None),
    ("mirror destination", "mirror", "destination", _port_or_none),
    ("mirror sources", "mirror", "sources", _ports),
    ("management mode", "management", "mode", None),
    ("TFTP", "management", "tftp", None),
    ("power saving", "management", "power_saving", None),
    ("loop detection", "management", "loop_detection", None),
)

_PORT_SETTINGS: tuple[tuple[str, str, Callable[[Any], str] | None], ...] = (
    ("description", "description", _none),
    ("speed setting", "speed_setting", None),
    ("flow control", "flow_control", None),
)


def _change_text(label: str, old: Any, new: Any, fmt: Callable[[Any], str] | None) -> str | None:
    if old == new:
        return None
    if isinstance(new, bool):
        return f"{PREFIX}{label} turned {_on_off(new)}"
    fmt = fmt or str
    return f"{PREFIX}{label} {fmt(old)} → {fmt(new)}"


def _group_changes(prev: Snapshot, cur: Snapshot) -> Iterator[str | None]:
    for label, group, attr, fmt in _CONFIG_SETTINGS:
        old, new = getattr(prev, group), getattr(cur, group)
        if old is not None and new is not None:
            yield _change_text(label, getattr(old, attr), getattr(new, attr), fmt)


def _config(texts: Iterator[str | None]) -> list[Change]:
    return [Change(ChangeKind.CONFIG, t) for t in texts if t is not None]


def _per_port(
    prev_items: Sequence[Any], cur_items: Sequence[Any], key: Callable[[Any], int]
) -> Iterator[tuple[int, Any, Any]]:
    old = {key(i): i for i in prev_items}
    for item in cur_items:
        before = old.get(key(item))
        if before is not None:
            yield key(item), before, item


def _port_changes(prev: Snapshot, cur: Snapshot) -> list[Change]:
    changes: list[Change] = []
    for n, old, new in _per_port(prev.ports, cur.ports, lambda p: p.port):
        if not old.up and new.up:
            speed = f" at {new.link_mbps} Mb/s" if new.link_mbps is not None else ""
            changes.append(Change(ChangeKind.LINK_UP, f"{PREFIX}port {n} link up{speed}", n))
        elif old.up and not new.up:
            changes.append(Change(ChangeKind.LINK_DOWN, f"{PREFIX}port {n} link down", n))
        elif (
            old.up
            and old.link_mbps is not None
            and new.link_mbps is not None
            and old.link_mbps != new.link_mbps
        ):
            speed_text = f"{PREFIX}port {n} speed {old.link_mbps} → {new.link_mbps} Mb/s"
            changes.append(Change(ChangeKind.SPEED, speed_text, n))
        for label, attr, fmt in _PORT_SETTINGS:
            text = _change_text(f"port {n} {label}", getattr(old, attr), getattr(new, attr), fmt)
            if text is not None:
                changes.append(Change(ChangeKind.CONFIG, text, n))
    return changes


def _vlan_changes(prev: Snapshot, cur: Snapshot) -> Iterator[str | None]:
    if prev.vlans is None or cur.vlans is None:
        return
    for n, old, new in _per_port(prev.vlans.pvids, cur.vlans.pvids, lambda t: t[0]):
        yield _change_text(f"port {n} PVID", old[1], new[1], None)
    for vid in sorted(set(cur.vlans.vlan_ids) - set(prev.vlans.vlan_ids)):
        yield f"{PREFIX}VLAN {vid} added"
    for vid in sorted(set(prev.vlans.vlan_ids) - set(cur.vlans.vlan_ids)):
        yield f"{PREFIX}VLAN {vid} removed"
    old_m, new_m = prev.vlans.shown, cur.vlans.shown
    if old_m is not None and new_m is not None and old_m.vid == new_m.vid:
        for i, (a, b) in enumerate(zip(old_m.members, new_m.members, strict=False), start=1):
            if a != b:
                yield f"{PREFIX}VLAN {new_m.vid} port {i} membership {_none(a)} → {_none(b)}"


def _rate_limit_changes(prev: Snapshot, cur: Snapshot) -> Iterator[str | None]:
    if prev.qos is None or cur.qos is None:
        return
    for n, old, new in _per_port(prev.qos.rate_limits, cur.qos.rate_limits, lambda r: r.port):
        for label, a, b in (
            ("ingress", old.ingress_kbps, new.ingress_kbps),
            ("egress", old.egress_kbps, new.egress_kbps),
        ):
            if a != b:
                yield f"{PREFIX}port {n} {label} limit {_kbps(a)} → {_kbps(b)}"


def _firmware_changes(prev: Snapshot, cur: Snapshot) -> list[Change]:
    if prev.info is None or cur.info is None or prev.info.firmware == cur.info.firmware:
        return []
    text = f"{PREFIX}firmware {prev.info.firmware} → {cur.info.firmware}"
    return [Change(ChangeKind.FIRMWARE, text)]


def _access_changes(prev: Snapshot, cur: Snapshot, own_ip: str | None) -> list[Change]:
    if prev.management is None or cur.management is None:
        return []
    old, new = prev.management.access_list, cur.management.access_list
    if old == new:
        return []
    if own_ip is not None and not ip_allowed(own_ip, new):
        text = (
            f"{PREFIX}Access Control no longer includes netview's address {own_ip}; "
            "the next login may be refused"
        )
        return [Change(ChangeKind.ACCESS_LIST, text)]
    return [Change(ChangeKind.CONFIG, f"{PREFIX}Access Control list changed")]


def diff(prev: Snapshot | None, cur: Snapshot, *, own_ip: str | None) -> list[Change]:
    """Changes from ``prev`` to ``cur``. A group is compared only when both snapshots hold it."""
    if prev is None:
        return []
    changes: list[Change] = []
    both = prev.groups & cur.groups
    if "status" in both:
        changes.extend(_port_changes(prev, cur))
    if "config" in both:
        changes.extend(_firmware_changes(prev, cur))
        changes.extend(_config(_group_changes(prev, cur)))
        changes.extend(_config(_vlan_changes(prev, cur)))
        changes.extend(_config(_rate_limit_changes(prev, cur)))
        changes.extend(_access_changes(prev, cur, own_ip))
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
