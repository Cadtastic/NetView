from __future__ import annotations

import json
from pathlib import Path

import pytest

from netview.plugins.builtin.gsm7248 import mibs
from netview.plugins.builtin.gsm7248.model import (
    GROUP_FIELDS,
    Health,
    LagGroup,
    Snapshot,
    snapshot_from_json,
    snapshot_to_json,
)
from netview.sdk import Oid, SnmpValue
from netview.sdk.testing.snmpwalk import parse_snmpwalk

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "gsm7248" / "walk_basic.txt"


def _full_snapshot() -> Snapshot:
    rows = parse_snmpwalk(FIXTURE.read_text(encoding="utf-8"))

    def under(prefix: Oid) -> list[tuple[Oid, SnmpValue]]:
        return [(o, v) for o, v in rows if o[: len(prefix)] == prefix]

    bridge = mibs.decode_bridge_ports(under(mibs.DOT1D_BASE_PORT_IFINDEX))
    ports = mibs.decode_ports(under(mibs.IF_TABLE), under(mibs.IF_X_TABLE), under(mibs.DOT3_STATS_DUPLEX))
    scalars = (
        mibs.SYS_DESCR,
        mibs.SYS_OBJECT_ID,
        mibs.SYS_UPTIME,
        mibs.SYS_NAME,
        mibs.DOT1D_BASE_BRIDGE_ADDRESS,
    )
    return Snapshot(
        t_ms=1_700_000_000_000,
        groups=frozenset({"status", "bridge", "topology"}),
        info=mibs.decode_system([(o, v) for o, v in rows if o in scalars]),
        health=Health(12.5, 2300, 61224),
        inventory=mibs.decode_entity(under(mibs.ENT_PHYSICAL_TABLE)),
        ports=tuple(ports),
        macs=tuple(mibs.decode_fdb(under(mibs.DOT1Q_TP_FDB_PORT), under(mibs.DOT1Q_TP_FDB_STATUS), bridge)),
        vlans=tuple(
            mibs.decode_vlans(
                under(mibs.DOT1Q_VLAN_STATIC_NAME),
                under(mibs.DOT1Q_VLAN_CURRENT_EGRESS),
                under(mibs.DOT1Q_VLAN_CURRENT_UNTAGGED),
                bridge,
            )
        ),
        pvids=tuple(sorted(mibs.decode_pvids(under(mibs.DOT1Q_PVID), bridge).items())),
        stp=tuple(mibs.decode_stp(under(mibs.DOT1D_STP_PORT_STATE), bridge)),
        lags=(LagGroup(49, "1/1", frozenset({3, 4})),),
    )


def test_snapshot_round_trip() -> None:
    snap = _full_snapshot()
    assert snapshot_from_json(snapshot_to_json(snap)) == snap


def test_partial_snapshot_round_trip() -> None:
    snap = Snapshot(
        t_ms=5,
        groups=frozenset({"bridge"}),
        info=None,
        health=None,
        inventory=None,
        ports=(),
        macs=(),
        vlans=(),
        pvids=(),
        stp=(),
        lags=(),
    )
    back = snapshot_from_json(snapshot_to_json(snap))
    assert back == snap
    assert back.groups == frozenset({"bridge"})


def test_codec_output_is_deterministic() -> None:
    snap = _full_snapshot()
    assert snapshot_to_json(snap) == snapshot_to_json(snapshot_from_json(snapshot_to_json(snap)))


def test_codec_rejects_unknown_schema() -> None:
    data = json.loads(snapshot_to_json(_full_snapshot()))
    data["schema"] = "netview.gsm7248.snapshot/2"
    with pytest.raises(ValueError, match="schema"):
        snapshot_from_json(json.dumps(data))
    del data["schema"]
    with pytest.raises(ValueError, match="schema"):
        snapshot_from_json(json.dumps(data))


def test_snapshot_lookups() -> None:
    snap = _full_snapshot()
    port = snap.port(5)
    assert port is not None
    assert port.name == "0/5"
    assert snap.port_by_name("0/5") == port
    assert snap.port(999) is None
    assert snap.port_by_name("9/9") is None
    assert snap.pvid(5) == 1
    assert snap.pvid(49) is None


def test_group_fields_are_disjoint_and_as_specified() -> None:
    owned = [f for fields in GROUP_FIELDS.values() for f in fields]
    assert len(owned) == len(set(owned))
    assert GROUP_FIELDS["status"] == ("info", "health", "ports")
    assert GROUP_FIELDS["bridge"] == ("macs",)
    assert GROUP_FIELDS["topology"] == ("inventory", "vlans", "pvids", "stp", "lags")
