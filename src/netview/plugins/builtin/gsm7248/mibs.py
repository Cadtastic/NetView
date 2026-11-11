"""OID constants and pure decoders from SNMP walk rows to the plugin's model types.

Table constants are the OID of the table *entry* (so a column is ``ENTRY + (column,)``) unless the name
says it is a single column. Decoders take the rows of a walk below that OID and ignore any row that
is not the shape they expect.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from netview.sdk import Oid, SnmpValue

from .model import (
    Duplex,
    Health,
    Inventory,
    LagGroup,
    MacEntry,
    MacStatus,
    Port,
    PortCounters,
    PortKind,
    StpPort,
    StpState,
    SwitchInfo,
    Vlan,
)

Rows = Sequence[tuple[Oid, SnmpValue]]

# SNMPv2-MIB system group and BRIDGE-MIB base address (scalars)
SYS_DESCR: Oid = (1, 3, 6, 1, 2, 1, 1, 1, 0)
SYS_OBJECT_ID: Oid = (1, 3, 6, 1, 2, 1, 1, 2, 0)
SYS_UPTIME: Oid = (1, 3, 6, 1, 2, 1, 1, 3, 0)
SYS_NAME: Oid = (1, 3, 6, 1, 2, 1, 1, 5, 0)
DOT1D_BASE_BRIDGE_ADDRESS: Oid = (1, 3, 6, 1, 2, 1, 17, 1, 1, 0)

# IF-MIB: ifEntry and ifXEntry
IF_TABLE: Oid = (1, 3, 6, 1, 2, 1, 2, 2, 1)
IF_X_TABLE: Oid = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1)

# BRIDGE-MIB columns
DOT1D_BASE_PORT_IFINDEX: Oid = (1, 3, 6, 1, 2, 1, 17, 1, 4, 1, 2)
DOT1D_STP_PORT_STATE: Oid = (1, 3, 6, 1, 2, 1, 17, 2, 15, 1, 3)
DOT1D_TP_FDB_PORT: Oid = (1, 3, 6, 1, 2, 1, 17, 4, 3, 1, 2)  # the fallback
DOT1D_TP_FDB_STATUS: Oid = (1, 3, 6, 1, 2, 1, 17, 4, 3, 1, 3)

# Q-BRIDGE-MIB columns
DOT1Q_TP_FDB_PORT: Oid = (1, 3, 6, 1, 2, 1, 17, 7, 1, 2, 2, 1, 2)
DOT1Q_TP_FDB_STATUS: Oid = (1, 3, 6, 1, 2, 1, 17, 7, 1, 2, 2, 1, 3)
DOT1Q_VLAN_STATIC_NAME: Oid = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 3, 1, 1)
DOT1Q_VLAN_CURRENT_EGRESS: Oid = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 2, 1, 4)
DOT1Q_VLAN_CURRENT_UNTAGGED: Oid = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 2, 1, 5)
DOT1Q_PVID: Oid = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 5, 1, 1)

# Etherlike-MIB dot3StatsDuplexStatus (column)
DOT3_STATS_DUPLEX: Oid = (1, 3, 6, 1, 2, 1, 10, 7, 2, 1, 19)

# LAG-MIB dot3adAggPortAttachedAggID (column, indexed by the member's ifIndex)
DOT3AD_AGG_PORT_ATTACHED: Oid = (1, 2, 840, 10006, 300, 43, 1, 2, 1, 1, 13)

# ENTITY-MIB entPhysicalEntry
ENT_PHYSICAL_TABLE: Oid = (1, 3, 6, 1, 2, 1, 47, 1, 1, 1, 1)

# NETGEAR-SWITCHING-MIB (fastPathSwitching, 1.3.6.1.4.1.4526.10.1). Checked against the MIB text (LibreNMS
# copy, 2014 revision) and a live GSM7248 on firmware 6.3.3.7, which fills these where the standard
# MIBs are blank.
_NG = (1, 3, 6, 1, 4, 1, 4526, 10, 1)
# agentInventoryGroup (agentInfoGroup 1): agentInventorySerialNumber and agentInventorySoftwareVersion
NG_INV_SERIAL: Oid = (*_NG, 1, 1, 4, 0)
NG_INV_SOFTWARE_VERSION: Oid = (*_NG, 1, 1, 13, 0)
# agentSwitchCpuProcessMemFree, KB. 6.3.3.7 has the old layout of agentSwitchCpuProcessGroup at
# agentInfoGroup 5 (MemFree 1, MemAvailable 2, per-process table 3); the 2014 MIB moved it to group 4.
NG_MEM_FREE: Oid | None = (*_NG, 1, 5, 1, 0)
# 6.3.3.7 has no total-utilisation object (its process table holds shares that add up to 100%), and its
# MemAvailable (1420 against 61224 free) is not a total. An OID is never guessed, so these stay None.
NG_CPU_UTIL: Oid | None = None
NG_MEM_TOTAL: Oid | None = None
# agentStpSwitchConfigGroup (agentConfigGroup 15): agentStpCstPortForwardingState, indexed by ifIndex.
# 6.3.3.7 runs MSTP and leaves the BRIDGE-MIB dot1dStpPortTable empty.
NG_STP_CST_PORT_FORWARDING_STATE: Oid = (*_NG, 2, 15, 9, 1, 5)

_IF_TYPE_ETHERNET = 6
_IF_TYPE_LAG = 161
_ENT_CLASS_CHASSIS = 3

_STP_STATES: Mapping[int, StpState] = {
    1: "disabled",
    2: "blocking",
    3: "listening",
    4: "learning",
    5: "forwarding",
    6: "broken",
}
# discarding(1) learning(2) forwarding(3) disabled(4) manualFwd(5) notParticipate(6)
_CST_STATES: Mapping[int, StpState] = {
    1: "blocking",
    2: "learning",
    3: "forwarding",
    4: "disabled",
    5: "forwarding",
    6: "disabled",
}
_FDB_STATUS: Mapping[int, MacStatus] = {1: "other", 3: "learned", 4: "self", 5: "mgmt"}
_DUPLEX: Mapping[int, Duplex] = {1: "unknown", 2: "half", 3: "full"}


# helpers ---------------------------------------------------------------------------------------------


def _int(value: SnmpValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: SnmpValue) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _mac(octets: Sequence[int]) -> str | None:
    if len(octets) != 6 or any(not 0 <= o <= 255 for o in octets):
        return None
    return ":".join(f"{o:02x}" for o in octets)


def _below(rows: Rows, prefix: Oid, index_len: int) -> dict[tuple[int, ...], SnmpValue]:
    """Rows under ``prefix`` whose remaining index has exactly ``index_len`` parts, keyed by that index."""
    n = len(prefix)
    return {o[n:]: v for o, v in rows if len(o) == n + index_len and o[:n] == prefix}


def _column(rows: Rows, entry: Oid, column: int) -> dict[int, SnmpValue]:
    """A single-index table column as ``{index: value}``."""
    return {k[0]: v for k, v in _below(rows, (*entry, column), 1).items()}


def _ints(column: Mapping[int, SnmpValue]) -> dict[int, int]:
    return {k: i for k, v in column.items() if (i := _int(v)) is not None}


def decode_portlist(octets: bytes) -> frozenset[int]:
    """Bridge port numbers in a PortList; bit 1 is the most significant bit of the first byte."""
    return frozenset(
        i * 8 + bit + 1 for i, byte in enumerate(octets) for bit in range(8) if byte & (0x80 >> bit)
    )


def _portlist_to_if(value: SnmpValue, bridge_ports: Mapping[int, int]) -> frozenset[int]:
    if not isinstance(value, bytes):
        return frozenset()
    return frozenset(bridge_ports[p] for p in decode_portlist(value) if p in bridge_ports)


# decoders --------------------------------------------------------------------------------------------


def decode_system(rows: Rows) -> SwitchInfo:
    by_oid = dict(rows)
    object_id = by_oid.get(SYS_OBJECT_ID)
    mac = by_oid.get(DOT1D_BASE_BRIDGE_ADDRESS)
    return SwitchInfo(
        sys_name=_text(by_oid.get(SYS_NAME)),
        sys_descr=_text(by_oid.get(SYS_DESCR)),
        object_id=".".join(map(str, object_id)) if isinstance(object_id, tuple) else "",
        uptime_cs=_int(by_oid.get(SYS_UPTIME)) or 0,
        mac=_mac(mac) if isinstance(mac, bytes) else None,
    )


def decode_ports(if_rows: Rows, ifx_rows: Rows, duplex_rows: Rows) -> list[Port]:
    descr = _column(if_rows, IF_TABLE, 2)
    if_type = _ints(_column(if_rows, IF_TABLE, 3))
    high_speed = _ints(_column(ifx_rows, IF_X_TABLE, 15))
    speed = _ints(_column(if_rows, IF_TABLE, 5))
    admin = _ints(_column(if_rows, IF_TABLE, 7))
    oper = _ints(_column(if_rows, IF_TABLE, 8))
    changed = _ints(_column(if_rows, IF_TABLE, 9))
    names = _column(ifx_rows, IF_X_TABLE, 1)
    aliases = _column(ifx_rows, IF_X_TABLE, 18)
    duplex = _ints({k[0]: v for k, v in _below(duplex_rows, DOT3_STATS_DUPLEX, 1).items()})

    ports: list[Port] = []
    for idx in sorted(set(descr) | set(if_type)):
        mbps = high_speed.get(idx)
        if mbps is None and idx in speed:
            mbps = speed[idx] // 1_000_000
        t = if_type.get(idx)
        kind: PortKind = "ethernet" if t == _IF_TYPE_ETHERNET else "lag" if t == _IF_TYPE_LAG else "other"
        ports.append(
            Port(
                if_index=idx,
                name=_text(names.get(idx)) or _text(descr.get(idx)) or f"if{idx}",
                alias=_text(aliases.get(idx)),
                kind=kind,
                admin_up=admin.get(idx) == 1,
                oper_up=oper.get(idx) == 1,
                speed_mbps=mbps if mbps else None,
                duplex=_DUPLEX.get(duplex.get(idx, 1), "unknown"),
                last_change_cs=changed.get(idx, 0),
            )
        )
    return ports


def decode_counters(if_rows: Rows, ifx_rows: Rows, t_ms: int) -> list[PortCounters]:
    def if_col(col: int) -> dict[int, int]:
        return _ints(_column(if_rows, IF_TABLE, col))

    def ifx_col(col: int) -> dict[int, int]:
        return _ints(_column(ifx_rows, IF_X_TABLE, col))

    hc_in, hc_out = ifx_col(6), ifx_col(10)
    # (64-bit column, 32-bit column) for each counter; the 32-bit side may live in ifTable or ifXTable
    in_octets = if_col(10)
    out_octets = if_col(16)
    cols: dict[str, tuple[dict[int, int], dict[int, int]]] = {
        "in_octets": (hc_in, in_octets),
        "out_octets": (hc_out, out_octets),
        "in_ucast": (ifx_col(7), if_col(11)),
        "out_ucast": (ifx_col(11), if_col(17)),
        "in_mcast": (ifx_col(8), ifx_col(2)),
        "out_mcast": (ifx_col(12), ifx_col(4)),
        "in_bcast": (ifx_col(9), ifx_col(3)),
        "out_bcast": (ifx_col(13), ifx_col(5)),
        "in_errors": ({}, if_col(14)),
        "out_errors": ({}, if_col(20)),
        "in_discards": ({}, if_col(13)),
        "out_discards": ({}, if_col(19)),
    }

    def pick(name: str, idx: int) -> int:
        wide, narrow = cols[name]
        return wide[idx] if idx in wide else narrow.get(idx, 0)

    result: list[PortCounters] = []
    for idx in sorted(set(hc_in) | set(in_octets)):
        result.append(
            PortCounters(
                if_index=idx,
                t_ms=t_ms,
                hc=idx in hc_in and idx in hc_out,
                **{name: pick(name, idx) for name in cols},
            )
        )
    return result


def decode_bridge_ports(rows: Rows) -> dict[int, int]:
    """Bridge port number to ifIndex."""
    return _ints(_column(rows, DOT1D_BASE_PORT_IFINDEX[:-1], DOT1D_BASE_PORT_IFINDEX[-1]))


def _entries(
    port_rows: Rows,
    status_rows: Rows | None,
    bridge_ports: Mapping[int, int],
    port_col: Oid,
    status_col: Oid,
    mac_at: int,
    vlan_of: Callable[[tuple[int, ...]], int],
) -> list[MacEntry]:
    ports = _below(port_rows, port_col, mac_at + 6)
    statuses = _below(status_rows, status_col, mac_at + 6) if status_rows is not None else {}
    out: list[MacEntry] = []
    for index in sorted(ports):
        mac = _mac(index[mac_at:])
        bridge_port = _int(ports[index])
        if mac is None or bridge_port is None:
            continue
        if_index = bridge_ports.get(bridge_port)
        raw = _int(statuses.get(index)) if index in statuses else None
        if raw == 2:  # invalid: the entry is being removed
            continue
        status: MacStatus = (
            _FDB_STATUS.get(raw, "other")
            if raw is not None
            else ("learned" if if_index is not None else "other")
        )
        out.append(MacEntry(mac=mac, vlan=vlan_of(index), if_index=if_index, status=status))
    return out


def decode_fdb(
    port_rows: Rows,
    status_rows: Rows,
    bridge_ports: Mapping[int, int],
    fdb_to_vlan: Mapping[int, int] | None = None,
) -> list[MacEntry]:
    """Q-BRIDGE forwarding table; indexes are ``(fdbId, m1..m6)``.

    Without ``fdb_to_vlan`` the fdbId is the VLAN id (independent VLAN learning, as FASTPATH does).
    """
    mapping = fdb_to_vlan or {}
    return _entries(
        port_rows,
        status_rows,
        bridge_ports,
        DOT1Q_TP_FDB_PORT,
        DOT1Q_TP_FDB_STATUS,
        1,
        lambda index: mapping.get(index[0], index[0]),
    )


def decode_fdb_dot1d(
    port_rows: Rows,
    bridge_ports: Mapping[int, int],
    status_rows: Rows | None = None,
) -> list[MacEntry]:
    """BRIDGE-MIB forwarding table, the fallback when Q-BRIDGE is empty; every entry is VLAN 1."""
    return _entries(
        port_rows, status_rows, bridge_ports, DOT1D_TP_FDB_PORT, DOT1D_TP_FDB_STATUS, 0, lambda _index: 1
    )


def decode_vlans(
    name_rows: Rows, egress_rows: Rows, untagged_rows: Rows, bridge_ports: Mapping[int, int]
) -> list[Vlan]:
    names = {k[0]: _text(v) for k, v in _below(name_rows, DOT1Q_VLAN_STATIC_NAME, 1).items()}
    # current-table indexes are (timeMark, vid)
    egress = {k[1]: v for k, v in _below(egress_rows, DOT1Q_VLAN_CURRENT_EGRESS, 2).items()}
    untagged = {k[1]: v for k, v in _below(untagged_rows, DOT1Q_VLAN_CURRENT_UNTAGGED, 2).items()}
    return [
        Vlan(
            vid=vid,
            name=names.get(vid, ""),
            egress=_portlist_to_if(egress.get(vid), bridge_ports),
            untagged=_portlist_to_if(untagged.get(vid), bridge_ports),
        )
        for vid in sorted(set(names) | set(egress))
    ]


def decode_pvids(rows: Rows, bridge_ports: Mapping[int, int]) -> dict[int, int]:
    """ifIndex to PVID."""
    pvids = _ints({k[0]: v for k, v in _below(rows, DOT1Q_PVID, 1).items()})
    return {bridge_ports[p]: v for p, v in pvids.items() if p in bridge_ports}


def decode_stp(rows: Rows, bridge_ports: Mapping[int, int]) -> list[StpPort]:
    states = _ints({k[0]: v for k, v in _below(rows, DOT1D_STP_PORT_STATE, 1).items()})
    return [
        StpPort(bridge_ports[p], _STP_STATES[s])
        for p, s in sorted(states.items())
        if p in bridge_ports and s in _STP_STATES
    ]


def decode_stp_cst(rows: Rows) -> list[StpPort]:
    """Port states from the NETGEAR MSTP CIST table (indexed by ifIndex), for when dot1dStp is empty."""
    states = _ints({k[0]: v for k, v in _below(rows, NG_STP_CST_PORT_FORWARDING_STATE, 1).items()})
    return [StpPort(i, _CST_STATES[s]) for i, s in sorted(states.items()) if s in _CST_STATES]


def decode_lags(rows: Rows, ports: Sequence[Port]) -> list[LagGroup]:
    """One group per aggregator interface (ifType 161), with the members attached to it."""
    attached = _ints({k[0]: v for k, v in _below(rows, DOT3AD_AGG_PORT_ATTACHED, 1).items()})
    return [
        LagGroup(
            if_index=p.if_index,
            name=p.name,
            members=frozenset(m for m, agg in attached.items() if agg == p.if_index),
        )
        for p in ports
        if p.kind == "lag"
    ]


def decode_entity(rows: Rows) -> Inventory:
    """Inventory from the chassis row (entPhysicalClass 3); the lowest-indexed chassis wins."""
    classes = _ints(_column(rows, ENT_PHYSICAL_TABLE, 5))
    chassis = sorted(i for i, c in classes.items() if c == _ENT_CLASS_CHASSIS)
    if not chassis:
        return Inventory(None, None, None)
    row = chassis[0]

    def field(*columns: int) -> str | None:
        for col in columns:
            text = _text(_column(rows, ENT_PHYSICAL_TABLE, col).get(row))
            if text:
                return text
        return None

    return Inventory(
        model=field(13, 2),  # entPhysicalModelName, else entPhysicalDescr
        serial=field(11),  # entPhysicalSerialNum
        firmware=field(10, 9),  # entPhysicalSoftwareRev, else entPhysicalFirmwareRev
    )


def merge_inventory(entity: Inventory, ng_rows: Rows) -> Inventory:
    """The entity inventory, with a blank serial or firmware filled from the NETGEAR inventory group."""
    by_oid = dict(ng_rows)
    return Inventory(
        model=entity.model,
        serial=entity.serial or _text(by_oid.get(NG_INV_SERIAL)) or None,
        firmware=entity.firmware or _text(by_oid.get(NG_INV_SOFTWARE_VERSION)) or None,
    )


def decode_health(rows: Rows) -> Health:
    by_oid = dict(rows)

    def number(oid: Oid | None) -> int | None:
        return None if oid is None else _int(by_oid.get(oid))

    cpu = number(NG_CPU_UTIL)
    return Health(
        cpu_percent=None if cpu is None else float(cpu),
        mem_free_kb=number(NG_MEM_FREE),
        mem_total_kb=number(NG_MEM_TOTAL),
    )
