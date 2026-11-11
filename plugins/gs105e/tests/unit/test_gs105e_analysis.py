"""Analysis rule tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from netview_local_plugins.gs105e.analysis import (
    ChangeKind,
    compute_rates,
    counters_reset,
    crc_alerts,
    diff,
    ip_allowed,
    merge_snapshot,
)
from netview_local_plugins.gs105e.model import (
    IgmpConfig,
    ManagementConfig,
    MirrorConfig,
    PortCounters,
    PortRates,
    PortStatus,
    QosConfig,
    RateLimit,
    Snapshot,
    SwitchInfo,
    VlanConfig,
    VlanMembers,
)

OWN = "192.168.1.50"


def _counters(port: int, t_ms: int, rx: int = 0, tx: int = 0, crc: int = 0) -> PortCounters:
    return PortCounters(port, t_ms, rx, tx, crc)


def _port(n: int, up: bool = False, mbps: int | None = None, **kw: Any) -> PortStatus:
    return replace(PortStatus(n, "", up, "Auto", mbps, False, 9216), **kw)


def _status(*ports: PortStatus, t_ms: int = 1) -> Snapshot:
    return Snapshot(t_ms, frozenset({"status"}), None, ports, None, None, None, None, None)


def _info(fw: str = "V2.00.03") -> SwitchInfo:
    return SwitchInfo("GS105Ev2", "sw", "S", "M", "B", fw, False, OWN, "255.255.255.0", "192.168.1.1")


def _config(
    *,
    fw: str = "V2.00.03",
    vlan_mode: Any = "off",
    pvid: int = 1,
    ingress: int | None = None,
    storm: bool = False,
    igmp: bool = True,
    mirror: bool = False,
    mgmt_mode: Any = "web",
    power: bool = False,
    loop: bool = True,
    access: tuple[tuple[str, str], ...] = (),
) -> Snapshot:
    return Snapshot(
        1,
        frozenset({"config"}),
        _info(fw),
        (),
        VlanConfig(vlan_mode, (1,), VlanMembers(1, ("U", "U")), ((2, pvid), (3, 1))),
        QosConfig("port", (RateLimit(2, ingress, None),), storm),
        IgmpConfig(igmp, None, False, False, None),
        MirrorConfig(mirror, 5 if mirror else None, (1,) if mirror else ()),
        ManagementConfig(mgmt_mode, False, access, power, loop),
    )


def test_rates_basic() -> None:
    r = compute_rates(_counters(1, 0), _counters(1, 15_000, rx=1_875_000, crc=3), 1000)
    assert r is not None
    assert r.in_bps == 1_000_000.0
    assert r.out_bps == 0.0
    assert r.crc_delta == 3
    assert r.util_percent == 0.1


def test_rates_none_cases() -> None:
    assert compute_rates(_counters(1, 0, rx=5), _counters(1, 1000, rx=4), 1000) is None
    assert compute_rates(_counters(1, 0, tx=5), _counters(1, 1000, tx=4), 1000) is None
    assert compute_rates(_counters(1, 0, crc=5), _counters(1, 1000, crc=4), 1000) is None
    assert compute_rates(_counters(1, 1000), _counters(1, 1000), 1000) is None


def test_rates_unknown_link() -> None:
    r = compute_rates(_counters(1, 0), _counters(1, 1000, rx=10), None)
    assert r is not None
    assert r.util_percent is None


def test_counters_reset() -> None:
    prev = {1: _counters(1, 0, rx=10), 2: _counters(2, 0, tx=5), 3: _counters(3, 0)}
    assert counters_reset(prev, [_counters(1, 1), _counters(2, 1), _counters(3, 1)])
    assert not counters_reset(prev, [_counters(1, 1), _counters(2, 1, tx=9), _counters(3, 1)])
    assert not counters_reset({1: _counters(1, 0)}, [_counters(1, 1)])


def _rates(port: int, crc: int) -> PortRates:
    return PortRates(port, 0, 0.0, 0.0, crc, None)


def test_crc_alerts_threshold_and_rate_limit() -> None:
    last: dict[int, int] = {}
    assert crc_alerts([_rates(1, 5)], 5, last, 1000) == []
    out = crc_alerts([_rates(1, 6), _rates(2, 0)], 5, last, 1000)
    assert len(out) == 1
    assert out[0].kind is ChangeKind.CRC
    assert out[0].port == 1
    assert out[0].text == "GS105E: port 1 CRC errors rising (6 in the last poll)"
    assert crc_alerts([_rates(1, 6)], 5, last, 1000 + 3_600_000) == []
    assert len(crc_alerts([_rates(1, 6)], 5, last, 1000 + 3_600_001)) == 1


def test_ip_allowed() -> None:
    assert ip_allowed(OWN, [])
    acl = [("192.168.1.0", "255.255.255.0")]
    assert ip_allowed(OWN, acl)
    assert not ip_allowed("10.0.0.5", acl)


def test_diff_baseline_empty() -> None:
    assert diff(None, _status(_port(1)), own_ip=OWN) == []


def test_diff_link_up_down_speed() -> None:
    down = _status(_port(3))
    up = _status(_port(3, True, 1000))
    changes = diff(down, up, own_ip=OWN)
    assert [(c.kind, c.text, c.port) for c in changes] == [
        (ChangeKind.LINK_UP, "GS105E: port 3 link up at 1000 Mb/s", 3)
    ]
    changes = diff(up, _status(_port(3, True, 100)), own_ip=OWN)
    assert [(c.kind, c.text) for c in changes] == [(ChangeKind.SPEED, "GS105E: port 3 speed 1000 → 100 Mb/s")]
    changes = diff(up, down, own_ip=OWN)
    assert [(c.kind, c.text) for c in changes] == [(ChangeKind.LINK_DOWN, "GS105E: port 3 link down")]


def test_diff_port_settings() -> None:
    a = _status(_port(2))
    b = _status(_port(2, flow_control=True, speed_setting="100M Full"))
    texts = [c.text for c in diff(a, b, own_ip=OWN)]
    assert texts == [
        "GS105E: port 2 speed setting Auto → 100M Full",
        "GS105E: port 2 flow control turned on",
    ]


def test_diff_config_texts() -> None:
    a = _config()
    b = _config(
        fw="V2.00.04",
        vlan_mode="advanced_8021q",
        pvid=20,
        ingress=65536,
        storm=True,
        igmp=False,
        mirror=True,
        mgmt_mode="web_and_utility",
        power=True,
        loop=False,
    )
    changes = diff(a, b, own_ip=OWN)
    texts = {c.text for c in changes}
    assert {
        "GS105E: firmware V2.00.03 → V2.00.04",
        "GS105E: VLAN mode off → advanced_8021q",
        "GS105E: port 2 PVID 1 → 20",
        "GS105E: port 2 ingress limit none → 65536 kbps",
        "GS105E: storm control turned on",
        "GS105E: IGMP snooping turned off",
        "GS105E: mirroring turned on",
        "GS105E: mirror destination none → port 5",
        "GS105E: mirror sources none → 1",
        "GS105E: management mode web → web_and_utility",
        "GS105E: power saving turned on",
        "GS105E: loop detection turned off",
    } <= texts
    kinds = {c.text: c.kind for c in changes}
    assert kinds["GS105E: firmware V2.00.03 → V2.00.04"] is ChangeKind.FIRMWARE
    assert kinds["GS105E: port 2 PVID 1 → 20"] is ChangeKind.CONFIG
    assert all(c.text.startswith("GS105E: ") for c in changes)
    assert diff(b, b, own_ip=OWN) == []


def test_diff_ignores_group_missing_on_one_side() -> None:
    assert diff(_status(_port(1)), _config(), own_ip=OWN) == []
    assert diff(_config(), _status(_port(1, True, 100)), own_ip=OWN) == []


def test_diff_access_list_excluding_own_ip() -> None:
    a = _config()
    b = _config(access=(("10.0.0.0", "255.255.255.0"),))
    changes = diff(a, b, own_ip=OWN)
    assert [(c.kind, c.text) for c in changes] == [
        (
            ChangeKind.ACCESS_LIST,
            f"GS105E: Access Control no longer includes netview's address {OWN}; "
            "the next login may be refused",
        )
    ]


def test_diff_access_list_still_allowing() -> None:
    a = _config()
    b = _config(access=(("192.168.1.0", "255.255.255.0"),))
    changes = diff(a, b, own_ip=OWN)
    assert [c.kind for c in changes] == [ChangeKind.CONFIG]


def test_merge_keeps_base_config() -> None:
    base = _config()
    merged = merge_snapshot(base, _status(_port(1, True, 100), t_ms=99))
    assert merged.t_ms == 99
    assert merged.groups == {"status", "config"}
    assert merged.vlans == base.vlans
    assert merged.info == base.info
    assert merged.ports[0].up
    assert merge_snapshot(None, base) is base
