from __future__ import annotations

import json

import pytest
from netview_local_plugins.gs105e.model import (
    GROUP_FIELDS,
    SCHEMA,
    IgmpConfig,
    ManagementConfig,
    MirrorConfig,
    PortStatus,
    QosConfig,
    RateLimit,
    Snapshot,
    SwitchInfo,
    VlanConfig,
    VlanMembers,
    snapshot_from_json,
    snapshot_to_json,
)


def _full() -> Snapshot:
    return Snapshot(
        t_ms=1_700_000_000_000,
        groups=frozenset({"status", "config"}),
        info=SwitchInfo(
            product="GS105Ev2",
            name="switch",
            serial="SERIAL",
            mac="00:11:22:33:44:55",
            bootloader="2.6.0.1",
            firmware="1.6.0.11",
            dhcp=False,
            ip="192.0.2.3",
            mask="255.255.255.0",
            gateway="192.0.2.1",
        ),
        ports=(
            PortStatus(1, "uplink", True, "Auto", 1000, True, 9216),
            PortStatus(2, "", False, "Disable", None, False, None),
        ),
        vlans=VlanConfig(
            mode="advanced_8021q",
            vlan_ids=(1, 20),
            shown=VlanMembers(20, ("U", "T", "", "?x", "U")),
            pvids=((1, 1), (2, 20)),
        ),
        qos=QosConfig(
            mode="port",
            rate_limits=(RateLimit(1, None, 512), RateLimit(2, 1024, None)),
            storm_control=True,
        ),
        igmp=IgmpConfig(True, 1, False, True, "3"),
        mirror=MirrorConfig(True, 5, (1, 2)),
        management=ManagementConfig("web", False, (("192.0.2.9", "255.255.255.255"),), True, False),
    )


def test_round_trip_full_snapshot() -> None:
    s = _full()
    assert snapshot_from_json(snapshot_to_json(s)) == s


def test_round_trip_partial_status_only() -> None:
    s = Snapshot(
        t_ms=5,
        groups=frozenset({"status"}),
        info=None,
        ports=(PortStatus(1, "", True, "Auto", 100, False, None),),
        vlans=None,
        qos=None,
        igmp=None,
        mirror=None,
        management=None,
    )
    assert snapshot_from_json(snapshot_to_json(s)) == s


def test_port_lookup_and_group_fields() -> None:
    s = _full()
    assert s.port(2) == s.ports[1]
    assert s.port(9) is None
    assert GROUP_FIELDS["status"] == ("ports",)
    assert "info" in GROUP_FIELDS["config"]


def test_wrong_schema_raises() -> None:
    doc = json.loads(snapshot_to_json(_full()))
    doc["schema"] = "netview.gs105e.snapshot/0"
    with pytest.raises(ValueError, match="schema"):
        snapshot_from_json(json.dumps(doc))
    assert SCHEMA == "netview.gs105e.snapshot/1"


def test_bad_literal_raises() -> None:
    doc = json.loads(snapshot_to_json(_full()))
    doc["vlans"]["mode"] = "weird"
    with pytest.raises(ValueError, match="weird"):
        snapshot_from_json(json.dumps(doc))


def test_malformed_body_raises() -> None:
    doc = json.loads(snapshot_to_json(_full()))
    del doc["ports"]
    with pytest.raises(ValueError, match="malformed"):
        snapshot_from_json(json.dumps(doc))
