from __future__ import annotations

from typing import Any

import pytest
from netview_local_plugins.gsm7248.analysis import (
    Attachment,
    Change,
    ChangeKind,
    attribute,
    compute_rates,
    detect_uplinks,
    diff,
    merge_snapshot,
    rebooted,
    single_device_ports,
)
from netview_local_plugins.gsm7248.model import (
    Health,
    Inventory,
    MacEntry,
    PollGroup,
    Port,
    PortCounters,
    Snapshot,
    StpPort,
    SwitchInfo,
)

GW = "aa:aa:aa:aa:aa:01"
NO_UPLINKS: frozenset[int] = frozenset()
ALL_GROUPS: frozenset[PollGroup] = frozenset({"status", "bridge", "topology"})


def counters(
    t_ms: int, octets_in: int = 0, octets_out: int = 0, *, hc: bool = True, **kw: int
) -> PortCounters:
    values = {
        "in_ucast": 0,
        "out_ucast": 0,
        "in_mcast": 0,
        "out_mcast": 0,
        "in_bcast": 0,
        "out_bcast": 0,
        "in_errors": 0,
        "out_errors": 0,
        "in_discards": 0,
        "out_discards": 0,
    }
    values.update(kw)
    return PortCounters(if_index=1, t_ms=t_ms, hc=hc, in_octets=octets_in, out_octets=octets_out, **values)


def port(i: int, *, up: bool = True, admin: bool = True, speed: int | None = 1000) -> Port:
    return Port(i, f"0/{i}", "", "ethernet", admin, up, speed if up else None, "full", 0)


def mac(m: str, i: int | None, vlan: int = 1, status: Any = "learned") -> MacEntry:
    return MacEntry(m, vlan, i, status)


def info(uptime: int) -> SwitchInfo:
    return SwitchInfo("sw", "d", "1.2", uptime, None)


def snap(
    t_ms: int = 1,
    groups: frozenset[PollGroup] = ALL_GROUPS,
    *,
    ports: tuple[Port, ...] = (),
    macs: tuple[MacEntry, ...] = (),
    stp: tuple[StpPort, ...] = (),
    uptime: int = 100,
    free: int | None = None,
) -> Snapshot:
    return Snapshot(
        t_ms=t_ms,
        groups=groups,
        info=info(uptime),
        health=Health(None, free, None),
        inventory=None,
        ports=ports,
        macs=macs,
        vlans=(),
        pvids=(),
        stp=stp,
        lags=(),
    )


def run(prev: Snapshot | None, cur: Snapshot, **kw: Any) -> list[Change]:
    args: dict[str, Any] = {
        "known_macs": frozenset(),
        "seen_macs": frozenset(),
        "uplinks": NO_UPLINKS,
        "low_memory_kb": 1000,
    }
    args.update(kw)
    return diff(prev, cur, **args)


def test_rates_basic() -> None:
    r = compute_rates(counters(0, 0, 0), counters(15_000, 18_750_000, 0), 1000)
    assert r is not None
    assert r.in_bps == 10_000_000
    assert r.out_bps == 0


def test_util_percent() -> None:
    r = compute_rates(counters(0), counters(15_000, 18_750_000), 1000)
    assert r is not None
    assert r.util_percent == 1.0


def test_util_unknown_speed() -> None:
    r = compute_rates(counters(0), counters(15_000, 1000), None)
    assert r is not None
    assert r.util_percent is None
    r = compute_rates(counters(0), counters(15_000, 1000), 0)
    assert r is not None
    assert r.util_percent is None


def test_counter_reset_returns_none() -> None:
    assert compute_rates(counters(0, 1000), counters(15_000, 10), 1000) is None


def test_32bit_wrap() -> None:
    r = compute_rates(counters(0, 2**32 - 1000, hc=False), counters(15_000, 500, hc=False), 1000)
    assert r is not None
    assert r.in_bps == 1500 * 8 / 15


def test_32bit_reset_is_not_a_spike() -> None:
    assert compute_rates(counters(0, 500_000_000, hc=False), counters(15_000, 10, hc=False), 1000) is None


def test_32bit_reset_unknown_speed() -> None:
    assert compute_rates(counters(0, 2_000_000_000, hc=False), counters(15_000, 10, hc=False), None) is None
    assert compute_rates(counters(0, 2**32 - 10, hc=False), counters(15_000, 10, hc=False), None) is not None


@pytest.mark.parametrize("speed", [None, 1000])
@pytest.mark.parametrize("field", ["in_errors", "out_errors", "in_discards", "out_discards"])
def test_32bit_error_counter_reset_is_not_a_spike(field: str, speed: int | None) -> None:
    prev = counters(0, 3_000_000_000, 3_000_000_000, hc=False, **{field: 50})
    cur = counters(15_000, 10, 10, hc=False, **{field: 0})
    assert compute_rates(prev, cur, speed) is None


def test_same_timestamp_returns_none() -> None:
    assert compute_rates(counters(5), counters(5), 1000) is None


def test_error_rates() -> None:
    r = compute_rates(counters(0), counters(10_000, in_errors=20, out_discards=5), 1000)
    assert r is not None
    assert r.in_err_ps == 2
    assert r.out_disc_ps == 0.5


def test_reboot_detected_from_uptime() -> None:
    assert rebooted(info(500), info(10))
    assert not rebooted(info(10), info(500))
    assert not rebooted(None, info(10))


def test_uplink_by_threshold() -> None:
    macs = tuple(mac(f"02:00:00:00:00:{i:02x}", 5) for i in range(9))
    s = snap(ports=(port(5),), macs=macs)
    assert detect_uplinks(s, None, frozenset(), 8) == {5}
    assert detect_uplinks(s, None, frozenset(), 9) == frozenset()


def test_uplink_by_gateway_mac() -> None:
    s = snap(ports=(port(2), port(3)), macs=(mac(GW, 2), mac("02:00:00:00:00:09", 3)))
    assert detect_uplinks(s, GW, frozenset(), 8) == {2}


def test_uplink_configured() -> None:
    s = snap(ports=(port(2), port(3)))
    assert detect_uplinks(s, None, frozenset({"0/3"}), 8) == {3}


def test_attribute_marks_via_uplink() -> None:
    s = snap(
        ports=(port(2), port(3)),
        macs=(mac("m1", 2), mac("m2", 3), mac("m3", None, status="self"), mac("m4", 3, status="mgmt")),
    )
    out = attribute(s, frozenset({2}), {"m2": "dev-b"})
    assert out == [
        Attachment("m1", 2, "0/2", 1, True, None),
        Attachment("m2", 3, "0/3", 1, False, "dev-b"),
    ]


def test_multi_mac_port_not_single_device() -> None:
    s = snap(ports=(port(5),), macs=tuple(mac(f"m{i}", 5) for i in range(6)))
    keys = {f"m{i}": f"d{i}" for i in range(6)}
    assert single_device_ports(attribute(s, NO_UPLINKS, keys)) == {}


def test_single_device_port() -> None:
    s = snap(ports=(port(3), port(4), port(5)), macs=(mac("m1", 3), mac("m2", 4), mac("m3", 5), mac("m4", 5)))
    out = single_device_ports(attribute(s, frozenset({5}), {"m1": "dev1", "m3": "dev3"}))
    assert out == {3: "dev1"}  # 4 has an unknown MAC, 5 is an uplink


def test_first_snapshot_no_changes() -> None:
    assert run(None, snap(macs=(mac("m1", 3),), ports=(port(3),))) == []


def test_link_down_and_up_text() -> None:
    up, down = snap(ports=(port(3),)), snap(ports=(port(3, up=False),))
    [c] = run(up, down)
    assert (c.kind, c.text, c.if_index) == (ChangeKind.LINK_DOWN, "GSM7248 port 0/3 link down", 3)
    [c] = run(down, up)
    assert (c.kind, c.text) == (ChangeKind.LINK_UP, "GSM7248 port 0/3 link up at 1000 Mb/s")


def test_admin_changed_text() -> None:
    [c] = run(snap(ports=(port(3),)), snap(ports=(port(3, admin=False),)))
    assert (c.kind, c.text) == (ChangeKind.ADMIN_CHANGED, "GSM7248 port 0/3 disabled")


def test_rebooted_change() -> None:
    [c] = run(snap(uptime=500), snap(uptime=5))
    assert (c.kind, c.text) == (ChangeKind.REBOOTED, "GSM7248 restarted")


def test_mac_gone_only_for_known_devices() -> None:
    prev = snap(ports=(port(3),), macs=(mac("known", 3), mac("guest", 3)))
    cur = snap(ports=(port(3),), macs=())
    [c] = run(prev, cur, known_macs=frozenset({"known"}))
    assert (c.kind, c.text, c.mac) == (ChangeKind.MAC_GONE, "known left GSM7248 port 0/3", "known")


def test_mac_new_only_when_never_seen() -> None:
    prev = snap(ports=(port(3),), macs=())
    cur = snap(ports=(port(3),), macs=(mac("old", 3), mac("fresh", 3, vlan=20)))
    out = run(prev, cur, seen_macs=frozenset({"old"}))
    assert [(c.kind, c.text) for c in out] == [
        (ChangeKind.MAC_NEW, "fresh appeared on GSM7248 port 0/3 (VLAN 20)")
    ]


def test_mac_new_not_on_uplink() -> None:
    prev = snap(ports=(port(3), port(4)), macs=())
    cur = snap(ports=(port(3), port(4)), macs=(mac("x", 4),))
    assert run(prev, cur, uplinks=frozenset({4})) == []


def test_mac_moved() -> None:
    prev = snap(ports=(port(3), port(4)), macs=(mac("x", 3),))
    cur = snap(ports=(port(3), port(4)), macs=(mac("x", 4),))
    [c] = run(prev, cur, seen_macs=frozenset({"x"}))
    assert (c.kind, c.text) == (ChangeKind.MAC_MOVED, "x moved from GSM7248 port 0/3 to 0/4")


def test_mac_move_via_uplink_ignored() -> None:
    prev = snap(ports=(port(3), port(4)), macs=(mac("x", 3),))
    cur = snap(ports=(port(3), port(4)), macs=(mac("x", 4),))
    assert run(prev, cur, seen_macs=frozenset({"x"}), uplinks=frozenset({4})) == []
    assert run(cur, prev, seen_macs=frozenset({"x"}), uplinks=frozenset({4})) == []


def test_stp_change() -> None:
    p = (port(3),)
    prev = snap(ports=p, stp=(StpPort(3, "forwarding"),))
    cur = snap(ports=p, stp=(StpPort(3, "blocking"),))
    [c] = run(prev, cur)
    assert (c.kind, c.text) == (
        ChangeKind.STP_CHANGED,
        "GSM7248 port 0/3 spanning tree forwarding → blocking",
    )


def test_low_memory_once() -> None:
    [c] = run(snap(free=5000), snap(free=800))
    assert (c.kind, c.text) == (ChangeKind.LOW_MEMORY, "GSM7248 memory low: 800 KB free")
    assert run(snap(free=800), snap(free=700)) == []
    assert run(snap(free=5000), snap(free=4000)) == []


def test_first_bridge_poll_after_status_emits_nothing() -> None:
    prev = snap(groups=frozenset({"status"}), ports=(port(3),))
    bridge_part = snap(groups=frozenset({"bridge"}), macs=tuple(mac(f"m{i}", 3) for i in range(6)))
    cur = merge_snapshot(prev, bridge_part)
    assert cur.groups == {"status", "bridge"}
    known = frozenset(f"m{i}" for i in range(6))
    assert run(prev, cur, known_macs=known) == []


def test_status_poll_keeps_pvid_and_firmware() -> None:
    base = Snapshot(
        1,
        ALL_GROUPS,
        info(1),
        None,
        Inventory("m", "s", "fw"),
        (),
        (),
        (),
        ((3, 7),),
        (),
        (),
    )
    part = Snapshot(2, frozenset({"status"}), info(2), None, None, (port(3),), (), (), (), (), ())
    merged = merge_snapshot(base, part)
    assert merged.pvids == ((3, 7),)
    assert merged.inventory == Inventory("m", "s", "fw")
    assert merged.ports == (port(3),)
    assert merged.t_ms == 2


def test_mac_table_can_become_empty() -> None:
    base = snap(ports=(port(3),), macs=(mac("known", 3),))
    part = snap(groups=frozenset({"bridge"}), macs=())
    merged = merge_snapshot(base, part)
    assert merged.macs == ()
    [c] = run(base, merged, known_macs=frozenset({"known"}))
    assert c.kind is ChangeKind.MAC_GONE


def test_merge_snapshot_keeps_base_fields() -> None:
    base = snap(ports=(port(3),), macs=(mac("a", 3),), stp=(StpPort(3, "forwarding"),))
    part = snap(t_ms=9, groups=frozenset({"bridge"}), macs=(mac("b", 3),))
    merged = merge_snapshot(base, part)
    assert merged.macs == (mac("b", 3),)
    assert merged.ports == base.ports
    assert merged.stp == base.stp
    assert merge_snapshot(None, part) is part
