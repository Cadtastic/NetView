from __future__ import annotations

from pathlib import Path

from netview.plugins.builtin.gsm7248 import mibs
from netview.plugins.builtin.gsm7248.collector import Collector
from netview.sdk import SnmpTarget, SnmpV2c
from netview.sdk.testing.fakes import FakeSnmpClient

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "gsm7248" / "walk_basic.txt"
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
