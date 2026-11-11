"""Reads the switch's pages for one poll group and turns them into model values."""

from __future__ import annotations

from .client import SwitchSession
from .model import PollGroup, PortCounters, Snapshot, VlanConfig
from .pages import (
    ACCESS_CONTROL,
    BROADCAST_FILTER,
    CONFIG_PAGES,
    GREEN,
    IGMP,
    LOOP,
    MIRROR,
    PLUS_UTILITY,
    PORT_STATISTICS,
    PORT_STATUS,
    PVID,
    QOS,
    RATE_LIMIT,
    SWITCH_INFO,
    VLAN_MEMBERSHIP,
    VLAN_MODE_PAGES,
    parse_igmp,
    parse_management,
    parse_mirror,
    parse_port_statistics,
    parse_port_status,
    parse_pvids,
    parse_qos,
    parse_switch_info,
    parse_vlan_membership,
    parse_vlan_mode,
)


def read_counters(session: SwitchSession, t_ms: int) -> tuple[PortCounters, ...]:
    return parse_port_statistics(session.get(PORT_STATISTICS), t_ms)


def read_status(session: SwitchSession, t_ms: int) -> Snapshot:
    ports = parse_port_status(session.get(PORT_STATUS))
    groups: frozenset[PollGroup] = frozenset({"status"})
    return Snapshot(t_ms, groups, None, ports, None, None, None, None, None)


def read_config(session: SwitchSession, t_ms: int) -> Snapshot:
    """Every config page, once each: the switch info first, then ``CONFIG_PAGES`` in order."""
    html = {path: session.get(path) for path in (SWITCH_INFO, *CONFIG_PAGES)}
    mode = parse_vlan_mode({key: html[path] for key, path in VLAN_MODE_PAGES.items()})
    vlan_ids, shown = parse_vlan_membership(html[VLAN_MEMBERSHIP])
    groups: frozenset[PollGroup] = frozenset({"config"})
    return Snapshot(
        t_ms,
        groups,
        parse_switch_info(html[SWITCH_INFO]),
        (),
        VlanConfig(mode, vlan_ids, shown, parse_pvids(html[PVID])),
        parse_qos(html[QOS], html[RATE_LIMIT], html[BROADCAST_FILTER]),
        parse_igmp(html[IGMP]),
        parse_mirror(html[MIRROR]),
        parse_management(html[PLUS_UTILITY], html[ACCESS_CONTROL], html[GREEN], html[LOOP]),
    )
