from __future__ import annotations

from pathlib import Path

from netview_local_plugins.gsm7248 import mibs
from netview_local_plugins.gsm7248.model import Inventory, Port

from netview.sdk import Oid, SnmpValue
from netview.sdk.testing.snmpwalk import parse_snmpwalk

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "walk_basic.txt"

Rows = list[tuple[Oid, SnmpValue]]


def _all() -> Rows:
    return parse_snmpwalk(FIXTURE.read_text(encoding="utf-8"))


def _under(prefix: Oid) -> Rows:
    return [(o, v) for o, v in _all() if o[: len(prefix)] == prefix]


def _bridge_ports() -> dict[int, int]:
    return mibs.decode_bridge_ports(_under(mibs.DOT1D_BASE_PORT_IFINDEX))


def _ports() -> list[Port]:
    return mibs.decode_ports(_under(mibs.IF_TABLE), _under(mibs.IF_X_TABLE), _under(mibs.DOT3_STATS_DUPLEX))


def _port(name: str) -> Port:
    return next(p for p in _ports() if p.name == name)


def test_system_info() -> None:
    scalars = (
        mibs.SYS_DESCR,
        mibs.SYS_OBJECT_ID,
        mibs.SYS_UPTIME,
        mibs.SYS_NAME,
        mibs.DOT1D_BASE_BRIDGE_ADDRESS,
    )
    info = mibs.decode_system([(o, v) for o, v in _all() if o in scalars])
    assert info.object_id == "1.3.6.1.4.1.4526.100.2.1"
    assert info.mac == "00:1b:2f:c2:dc:75"
    assert info.sys_descr == "GSM7248 L2 Managed Gigabit Switch"
    assert info.sys_name == ""
    assert info.uptime_cs == 8640000


def test_entity_inventory() -> None:
    inv = mibs.decode_entity(_under(mibs.ENT_PHYSICAL_TABLE))
    assert inv.firmware == "6.3.3.7"
    assert inv.serial == "TEST-SERIAL-0001"
    assert inv.model == "GSM7248"


def test_ports_names_and_state() -> None:
    ports = _ports()
    assert len(ports) == 50
    p5 = _port("0/5")
    assert p5.oper_up is True
    assert p5.admin_up is True
    assert p5.speed_mbps == 1000
    assert p5.duplex == "full"
    assert p5.kind == "ethernet"
    p1 = _port("0/1")
    assert p1.oper_up is False
    assert p1.speed_mbps is None
    assert _port("1/1").kind == "lag"
    assert _port("3/1").kind == "other"


def test_portlist_msb_first() -> None:
    assert mibs.decode_portlist(bytes([0b1000_0000, 0b0000_0001])) == frozenset({1, 16})


def test_fdb_maps_to_ifindex_and_vlan() -> None:
    entries = mibs.decode_fdb(
        _under(mibs.DOT1Q_TP_FDB_PORT), _under(mibs.DOT1Q_TP_FDB_STATUS), _bridge_ports()
    )
    learned = [e for e in entries if e.status == "learned"]
    assert len(learned) == 6
    assert {e.if_index for e in learned} == {5}
    assert {e.vlan for e in learned} == {1}
    assert "b8:ca:3a:67:7d:ef" in {e.mac for e in learned}
    own = [e for e in entries if e.mac == "00:1b:2f:c2:dc:75"]
    assert [e.status for e in own] == ["self"]


def test_fdb_uses_vlan_map_when_given() -> None:
    entries = mibs.decode_fdb(
        _under(mibs.DOT1Q_TP_FDB_PORT),
        _under(mibs.DOT1Q_TP_FDB_STATUS),
        _bridge_ports(),
        fdb_to_vlan={1: 20},
    )
    assert {e.vlan for e in entries} == {20}


def test_fdb_dot1d_fallback() -> None:
    entries = mibs.decode_fdb_dot1d(_under(mibs.DOT1D_TP_FDB_PORT), _bridge_ports())
    learned = [e for e in entries if e.if_index == 5]
    assert len(learned) == 6
    assert {e.vlan for e in entries} == {1}
    assert {e.status for e in learned} == {"learned"}


def test_stp_states() -> None:
    stp = {s.if_index: s.state for s in mibs.decode_stp(_under(mibs.DOT1D_STP_PORT_STATE), _bridge_ports())}
    assert stp[7] == "blocking"
    assert stp[5] == "forwarding"
    assert stp[1] == "disabled"


def test_vlan_membership() -> None:
    vlans = mibs.decode_vlans(
        _under(mibs.DOT1Q_VLAN_STATIC_NAME),
        _under(mibs.DOT1Q_VLAN_CURRENT_EGRESS),
        _under(mibs.DOT1Q_VLAN_CURRENT_UNTAGGED),
        _bridge_ports(),
    )
    assert [v.vid for v in vlans] == [1]
    assert vlans[0].name == "default"
    assert vlans[0].untagged == frozenset(range(1, 49))
    assert vlans[0].egress == frozenset(range(1, 49))


def test_pvids() -> None:
    pvids = mibs.decode_pvids(_under(mibs.DOT1Q_PVID), _bridge_ports())
    assert pvids == dict.fromkeys(range(1, 49), 1)


def test_lags() -> None:
    lags = mibs.decode_lags(_under(mibs.DOT3AD_AGG_PORT_ATTACHED), _ports())
    assert [(g.if_index, g.name, g.members) for g in lags] == [(49, "1/1", frozenset())]
    rows: Rows = [((*mibs.DOT3AD_AGG_PORT_ATTACHED, 3), 49), ((*mibs.DOT3AD_AGG_PORT_ATTACHED, 4), 49)]
    assert mibs.decode_lags(rows, _ports())[0].members == frozenset({3, 4})


def test_counters_prefer_hc() -> None:
    counters = {
        c.if_index: c for c in mibs.decode_counters(_under(mibs.IF_TABLE), _under(mibs.IF_X_TABLE), 1234)
    }
    c5 = counters[5]
    assert c5.hc is True
    assert c5.t_ms == 1234
    assert c5.in_octets == 5_000_000_005
    assert c5.out_octets == 10_000_000_010


def test_counters_32bit_when_no_hc() -> None:
    hc_columns = {(*mibs.IF_X_TABLE, col) for col in (6, 7, 8, 9, 10, 11, 12, 13)}
    ifx = [(o, v) for o, v in _under(mibs.IF_X_TABLE) if o[: len(mibs.IF_X_TABLE) + 1] not in hc_columns]
    counters = {c.if_index: c for c in mibs.decode_counters(_under(mibs.IF_TABLE), ifx, 0)}
    c5 = counters[5]
    assert c5.hc is False
    assert c5.in_octets == 5 * 1000003
    assert c5.out_octets == 2 * 5 * 1000003


def test_health_absent_oids_returns_none_fields() -> None:
    health = mibs.decode_health(_all())
    assert (health.cpu_percent, health.mem_free_kb, health.mem_total_kb) == (None, None, None)


def test_health_reads_free_memory_from_the_netgear_cpu_process_group() -> None:
    # captured from a GSM7248 on firmware 6.3.3.7: agentSwitchCpuProcessMemFree, old (agentInfoGroup 5) layout
    assert mibs.NG_MEM_FREE == (1, 3, 6, 1, 4, 1, 4526, 10, 1, 1, 5, 1, 0)
    health = mibs.decode_health([(mibs.NG_MEM_FREE, 61224)])
    assert health.mem_free_kb == 61224
    # no total-utilisation object on this firmware, and its "available" value is not a total: never guessed
    assert (health.cpu_percent, health.mem_total_kb) == (None, None)


def test_netgear_inventory_fills_what_the_entity_table_leaves_blank() -> None:
    entity = Inventory(model="GSM7248-000", serial=None, firmware=None)
    rows: Rows = [(mibs.NG_INV_SERIAL, b"1DU37A3700091"), (mibs.NG_INV_SOFTWARE_VERSION, b"6.3.3.7")]
    assert mibs.merge_inventory(entity, rows) == Inventory("GSM7248-000", "1DU37A3700091", "6.3.3.7")


def test_entity_values_win_over_the_netgear_inventory() -> None:
    entity = Inventory(model="M", serial="S", firmware="F")
    rows: Rows = [(mibs.NG_INV_SERIAL, b"other"), (mibs.NG_INV_SOFTWARE_VERSION, b"other")]
    assert mibs.merge_inventory(entity, rows) == entity
    assert mibs.merge_inventory(entity, [(mibs.NG_INV_SERIAL, None)]) == entity


def test_netgear_cst_port_states() -> None:
    col = mibs.NG_STP_CST_PORT_FORWARDING_STATE
    rows: Rows = [((*col, i), v) for i, v in [(1, 3), (2, 4), (7, 1), (8, 2), (9, 5), (10, 6), (11, 99)]]
    assert [(s.if_index, s.state) for s in mibs.decode_stp_cst(rows)] == [
        (1, "forwarding"),
        (2, "disabled"),
        (7, "blocking"),  # discarding
        (8, "learning"),
        (9, "forwarding"),  # manualFwd
        (10, "disabled"),  # notParticipate
    ]


def test_decoders_ignore_unexpected_rows() -> None:
    junk: Rows = [
        ((*mibs.IF_TABLE, 99, 1), 5),
        ((*mibs.IF_TABLE, 2), b"short-index"),
        ((*mibs.DOT1Q_TP_FDB_PORT, 1, 2), 3),
        ((*mibs.DOT1Q_VLAN_CURRENT_EGRESS, 7), b"\xff"),
        ((*mibs.DOT1D_STP_PORT_STATE, 1), "text"),
        ((*mibs.ENT_PHYSICAL_TABLE, 99, 1), 1),
        (mibs.DOT1Q_PVID, None),
    ]
    bridge = _bridge_ports()
    assert len(mibs.decode_ports(_under(mibs.IF_TABLE) + junk, _under(mibs.IF_X_TABLE), [])) == 50
    assert mibs.decode_fdb(junk, junk, bridge) == []
    assert mibs.decode_fdb_dot1d(junk, bridge) == []
    assert mibs.decode_vlans(junk, junk, junk, bridge) == []
    assert mibs.decode_stp(junk, bridge) == []
    assert mibs.decode_pvids(junk, bridge) == {}
    assert mibs.decode_entity(junk) == Inventory(None, None, None)
    assert mibs.decode_counters(junk, junk, 0) == []
    assert mibs.decode_bridge_ports(junk) == {}
