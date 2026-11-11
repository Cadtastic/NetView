"""Polls the switch through ``ctx.snmp`` and builds partial snapshots, one method per poll group."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from netview.sdk import Oid, SnmpClient, SnmpError, SnmpTarget, SnmpValue

from . import mibs
from .model import PollGroup, PortCounters, Snapshot, StpPort

Rows = list[tuple[Oid, SnmpValue]]

EMPTY_VIEW_TEXT = (
    "the switch answered, but this community or user can read nothing (empty SNMP view). "
    "Check its access on the switch"
)


class SnmpEmptyView(SnmpError):
    """The agent answered, but every system object is missing: the credentials may read nothing.

    An agent reports objects outside the view it grants as missing (noSuchObject, endOfMibView),
    so polling would quietly store empty data instead of failing.
    """

    def __init__(self, message: str = EMPTY_VIEW_TEXT) -> None:
        super().__init__(message)


_SCALARS: tuple[Oid, ...] = (
    mibs.SYS_DESCR,
    mibs.SYS_OBJECT_ID,
    mibs.SYS_UPTIME,
    mibs.SYS_NAME,
    mibs.DOT1D_BASE_BRIDGE_ADDRESS,
)
_SYSTEM: tuple[Oid, ...] = (mibs.SYS_DESCR, mibs.SYS_OBJECT_ID, mibs.SYS_UPTIME, mibs.SYS_NAME)
_HEALTH: tuple[Oid, ...] = tuple(o for o in (mibs.NG_CPU_UTIL, mibs.NG_MEM_FREE, mibs.NG_MEM_TOTAL) if o)

# ifTable / ifXTable columns each poll reads (never the whole tables)
_IF_STATUS = (2, 3, 5, 7, 8, 9)  # descr, type, speed, admin, oper, last change
_IFX_STATUS = (1, 15, 18)  # name, high speed, alias
_IF_NAMES = (2, 3)
_IFX_NAMES = (1,)
_IFX_HC = (6, 7, 8, 9, 10, 11, 12, 13)
_IF_ERRORS = (13, 14, 19, 20)  # discards and errors, in and out
_IF_NARROW = (10, 11, 16, 17)  # 32-bit octets and unicast, the fallback without HC counters
_IFX_NARROW = (2, 3, 4, 5)  # 32-bit multicast and broadcast


def _partial(t_ms: int, group: PollGroup, **fields: Any) -> Snapshot:
    values: dict[str, Any] = {
        "info": None,
        "health": None,
        "inventory": None,
        "ports": (),
        "macs": (),
        "vlans": (),
        "pvids": (),
        "stp": (),
        "lags": (),
    }
    values.update(fields)
    return Snapshot(t_ms=t_ms, groups=frozenset({group}), **values)


class Collector:
    def __init__(self, snmp: SnmpClient) -> None:
        self._snmp = snmp
        self._bridge_ports: dict[int, int] = {}

    # ---- helpers -------------------------------------------------------------------------------

    def _columns(self, target: SnmpTarget, entry: Oid, columns: Sequence[int]) -> Rows:
        rows: Rows = []
        for column in columns:
            rows.extend(self._snmp.walk(target, (*entry, column)))
        return rows

    def _refresh_bridge_ports(self, target: SnmpTarget) -> dict[int, int]:
        """Bridge port to ifIndex. An empty answer keeps the last good map."""
        decoded = mibs.decode_bridge_ports(self._snmp.walk(target, mibs.DOT1D_BASE_PORT_IFINDEX))
        if decoded:
            self._bridge_ports = decoded
        return self._bridge_ports

    # ---- poll groups ---------------------------------------------------------------------------

    def counters(self, target: SnmpTarget, t_ms: int, if_indexes: Collection[int]) -> list[PortCounters]:
        wanted = set(if_indexes)
        if not wanted:
            return []

        def keep(rows: Rows) -> Rows:
            return [(oid, v) for oid, v in rows if oid[-1] in wanted]

        ifx = keep(self._columns(target, mibs.IF_X_TABLE, _IFX_HC))
        iff = keep(self._columns(target, mibs.IF_TABLE, _IF_ERRORS))
        has_hc = any(oid[len(mibs.IF_X_TABLE)] == 6 for oid, _ in ifx)
        if not has_hc:
            iff += keep(self._columns(target, mibs.IF_TABLE, _IF_NARROW))
            ifx += keep(self._columns(target, mibs.IF_X_TABLE, _IFX_NARROW))
        return [c for c in mibs.decode_counters(iff, ifx, t_ms) if c.if_index in wanted]

    def status(self, target: SnmpTarget, t_ms: int) -> Snapshot:
        scalars = self._snmp.get(target, (*_SCALARS, *_HEALTH))
        if all(scalars.get(oid) is None for oid in _SYSTEM):
            raise SnmpEmptyView()  # every agent serves the system group to anyone allowed to read
        rows: Rows = list(scalars.items())
        if_rows = self._columns(target, mibs.IF_TABLE, _IF_STATUS)
        ifx_rows = self._columns(target, mibs.IF_X_TABLE, _IFX_STATUS)
        duplex_rows = self._snmp.walk(target, mibs.DOT3_STATS_DUPLEX)
        return _partial(
            t_ms,
            "status",
            info=mibs.decode_system(rows),
            health=mibs.decode_health(rows),
            ports=tuple(mibs.decode_ports(if_rows, ifx_rows, duplex_rows)),
        )

    def bridge(self, target: SnmpTarget, t_ms: int) -> Snapshot:
        bridge_ports = self._refresh_bridge_ports(target)
        macs = mibs.decode_fdb(
            self._snmp.walk(target, mibs.DOT1Q_TP_FDB_PORT),
            self._snmp.walk(target, mibs.DOT1Q_TP_FDB_STATUS),
            bridge_ports,
        )
        if not macs:  # the switch did not answer Q-BRIDGE: use the BRIDGE-MIB table
            macs = mibs.decode_fdb_dot1d(
                self._snmp.walk(target, mibs.DOT1D_TP_FDB_PORT),
                bridge_ports,
                self._snmp.walk(target, mibs.DOT1D_TP_FDB_STATUS),
            )
        return _partial(t_ms, "bridge", macs=tuple(macs))

    def _stp(self, target: SnmpTarget, bridge_ports: dict[int, int]) -> list[StpPort]:
        """BRIDGE-MIB port states, else the NETGEAR MSTP CIST table (6.3.x leaves dot1dStp empty)."""
        stp = mibs.decode_stp(self._snmp.walk(target, mibs.DOT1D_STP_PORT_STATE), bridge_ports)
        if stp:
            return stp
        return mibs.decode_stp_cst(self._snmp.walk(target, mibs.NG_STP_CST_PORT_FORWARDING_STATE))

    def topology(self, target: SnmpTarget, t_ms: int) -> Snapshot:
        bridge_ports = self._refresh_bridge_ports(target)
        names = self._columns(target, mibs.IF_TABLE, _IF_NAMES)
        names_x = self._columns(target, mibs.IF_X_TABLE, _IFX_NAMES)
        ports = mibs.decode_ports(names, names_x, [])
        pvids = mibs.decode_pvids(self._snmp.walk(target, mibs.DOT1Q_PVID), bridge_ports)
        return _partial(
            t_ms,
            "topology",
            inventory=mibs.merge_inventory(
                mibs.decode_entity(self._snmp.walk(target, mibs.ENT_PHYSICAL_TABLE)),
                list(self._snmp.get(target, (mibs.NG_INV_SERIAL, mibs.NG_INV_SOFTWARE_VERSION)).items()),
            ),
            vlans=tuple(
                mibs.decode_vlans(
                    self._snmp.walk(target, mibs.DOT1Q_VLAN_STATIC_NAME),
                    self._snmp.walk(target, mibs.DOT1Q_VLAN_CURRENT_EGRESS),
                    self._snmp.walk(target, mibs.DOT1Q_VLAN_CURRENT_UNTAGGED),
                    bridge_ports,
                )
            ),
            pvids=tuple(sorted(pvids.items())),
            stp=tuple(self._stp(target, bridge_ports)),
            lags=tuple(mibs.decode_lags(self._snmp.walk(target, mibs.DOT3AD_AGG_PORT_ATTACHED), ports)),
        )
