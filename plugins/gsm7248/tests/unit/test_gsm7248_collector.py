from __future__ import annotations

from pathlib import Path

import pytest
from netview_local_plugins.gsm7248 import mibs
from netview_local_plugins.gsm7248.collector import Collector

from netview.sdk import SnmpTarget, SnmpV2c
from netview.sdk.testing.fakes import FakeSnmpClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "walk_basic.txt"
TARGET = SnmpTarget("192.168.1.4", SnmpV2c("public"))


def _collector() -> tuple[Collector, FakeSnmpClient]:
    snmp = FakeSnmpClient.from_walk_file(FIXTURE)
    return Collector(snmp), snmp


def test_status_snapshot() -> None:
    collector, _ = _collector()
    snap = collector.status(TARGET, 1000)
    assert snap.groups == frozenset({"status"})
    assert snap.t_ms == 1000
    assert snap.info is not None
    assert snap.info.mac == "00:1b:2f:c2:dc:75"
    assert snap.health is not None
    assert snap.port_by_name("0/5") is not None
    assert snap.macs == ()


def test_bridge_snapshot_uses_qbridge() -> None:
    collector, _ = _collector()
    snap = collector.bridge(TARGET, 1000)
    assert snap.groups == frozenset({"bridge"})
    assert any(m.mac == "b8:ca:3a:67:7d:ef" and m.if_index == 5 and m.vlan == 1 for m in snap.macs)


def test_bridge_falls_back_to_dot1d_when_qbridge_is_empty() -> None:
    collector, snmp = _collector()
    snmp.rows = {
        oid: v
        for oid, v in snmp.rows.items()
        if oid[: len(mibs.DOT1Q_TP_FDB_PORT) - 1] != mibs.DOT1Q_TP_FDB_PORT[:-1]
    }
    snap = collector.bridge(TARGET, 1000)
    assert any(m.mac == "b8:ca:3a:67:7d:ef" and m.if_index == 5 for m in snap.macs)


def test_topology_snapshot() -> None:
    collector, _ = _collector()
    snap = collector.topology(TARGET, 1000)
    assert snap.groups == frozenset({"topology"})
    assert snap.vlans
    assert snap.stp
    assert snap.pvid(5) == 1
    assert snap.inventory is not None
    assert snap.inventory.model


def test_counters_only_for_requested_ports() -> None:
    collector, _ = _collector()
    counters = collector.counters(TARGET, 5000, [5, 6])
    assert sorted(c.if_index for c in counters) == [5, 6]
    five = next(c for c in counters if c.if_index == 5)
    assert five.t_ms == 5000
    assert five.hc is True
    assert five.in_octets == 5_000_000_005


def test_counters_with_no_ports_makes_no_call() -> None:
    collector, snmp = _collector()
    assert collector.counters(TARGET, 5000, []) == []
    assert snmp.calls == []


def test_counters_do_not_walk_whole_tables() -> None:
    collector, snmp = _collector()
    collector.counters(TARGET, 5000, [5])
    walked = [oid for kind, oid in snmp.calls if kind == "walk"]
    assert mibs.IF_TABLE not in walked
    assert mibs.IF_X_TABLE not in walked


def test_status_with_an_empty_view_raises() -> None:
    """The agent answered, but every system object is missing: the credentials can read nothing."""
    from netview_local_plugins.gsm7248.collector import SnmpEmptyView

    from netview.sdk import SnmpError

    snmp = FakeSnmpClient([])
    with pytest.raises(SnmpEmptyView) as excinfo:
        Collector(snmp).status(TARGET, 1000)
    assert isinstance(excinfo.value, SnmpError)
    assert "can read nothing" in str(excinfo.value)


def test_status_with_some_system_objects_is_fine() -> None:
    collector, snmp = _collector()
    snmp.rows = {oid: v for oid, v in snmp.rows.items() if oid != mibs.SYS_DESCR}
    assert collector.status(TARGET, 1000).info is not None


def test_topology_falls_back_to_the_netgear_cst_table_and_inventory() -> None:
    """A GSM7248 on 6.3.3.7 leaves the BRIDGE-MIB STP table empty and the entity serial and firmware blank."""
    collector, snmp = _collector()
    stp_col = mibs.DOT1D_STP_PORT_STATE
    ent = mibs.ENT_PHYSICAL_TABLE
    blank = {(*ent, 9), (*ent, 10), (*ent, 11)}
    snmp.rows = {
        oid: (b"" if oid[: len(ent) + 1] in blank else v)
        for oid, v in snmp.rows.items()
        if oid[: len(stp_col)] != stp_col
    }
    snmp.rows[(*mibs.NG_STP_CST_PORT_FORWARDING_STATE, 5)] = 3
    snmp.rows[(*mibs.NG_STP_CST_PORT_FORWARDING_STATE, 7)] = 1
    snmp.rows[mibs.NG_INV_SERIAL] = b"1DU37A3700091"
    snmp.rows[mibs.NG_INV_SOFTWARE_VERSION] = b"6.3.3.7"
    snap = collector.topology(TARGET, 1000)
    assert {(s.if_index, s.state) for s in snap.stp} == {(5, "forwarding"), (7, "blocking")}
    assert snap.inventory is not None
    assert (snap.inventory.serial, snap.inventory.firmware) == ("1DU37A3700091", "6.3.3.7")


def test_topology_prefers_the_bridge_mib_stp_table() -> None:
    collector, snmp = _collector()
    snmp.rows[(*mibs.NG_STP_CST_PORT_FORWARDING_STATE, 5)] = 1
    snap = collector.topology(TARGET, 1000)
    assert {s.if_index: s.state for s in snap.stp}[5] == "forwarding"


def test_status_reads_free_memory() -> None:
    collector, snmp = _collector()
    snmp.rows[mibs.NG_MEM_FREE] = 61224
    snap = collector.status(TARGET, 1000)
    assert snap.health is not None
    assert snap.health.mem_free_kb == 61224
