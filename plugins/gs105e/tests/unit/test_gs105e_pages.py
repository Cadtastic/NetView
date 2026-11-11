"""Parser tests against the captured pages of firmware 1.6.0.11."""

from __future__ import annotations

from pathlib import Path

import pytest
from netview_local_plugins.gs105e import pages
from netview_local_plugins.gs105e.model import (
    IgmpConfig,
    ManagementConfig,
    MirrorConfig,
    PortCounters,
    QosConfig,
    RateLimit,
    SwitchInfo,
    VlanMembers,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "fw-1.6.0.11"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_parse_login() -> None:
    page = pages.parse_login(load("login.cgi"))
    assert page.rand == "12345678"
    assert page.title == "NETGEAR GS105Ev2"
    assert page.firmware == "1.6.0.11"


def test_parse_login_without_rand_raises() -> None:
    with pytest.raises(pages.PageChanged) as err:
        pages.parse_login("<html><title>x</title></html>")
    assert err.value.page == "/login.cgi"


def test_is_login_page() -> None:
    assert pages.is_login_page(load("logged_out.html"))
    assert pages.is_login_page(load("login.cgi"))
    assert not pages.is_login_page(load("status.cgi"))


def test_page_changed_message() -> None:
    err = pages.PageChanged("/x.cgi", "no rows")
    assert str(err) == "/x.cgi: no rows"
    assert err.page == "/x.cgi"


def test_config_pages_order() -> None:
    assert pages.CONFIG_PAGES[0] == "/8021qBasic.cgi"
    assert len(pages.CONFIG_PAGES) == len(set(pages.CONFIG_PAGES)) == 15


def test_parse_switch_info() -> None:
    assert pages.parse_switch_info(load("switch_info.cgi")) == SwitchInfo(
        "GS105Ev2",
        "GS105E Switch",
        "SERIAL0000000",
        "02:00:00:00:00:01",
        "V1.6.0.2-VB",
        "V1.6.0.11",
        False,
        "192.0.2.1",
        "255.255.255.0",
        "192.0.2.2",
    )


def test_parse_port_status() -> None:
    ports = pages.parse_port_status(load("status.cgi"))
    assert [p.port for p in ports] == [1, 2, 3, 4, 5]
    for p in ports[:2]:
        assert p.up is True
        assert p.link_mbps == 1000
    for p in ports[2:]:
        assert p.up is False
        assert p.link_mbps is None
    for p in ports:
        assert p.speed_setting == "Auto"
        assert p.flow_control is False
        assert p.max_mtu == 16349
        assert p.description == ""


def test_parse_port_statistics() -> None:
    counters = pages.parse_port_statistics(load("portStatistics.cgi"), 1000)
    assert len(counters) == 5
    assert counters[0] == PortCounters(1, 1000, 5569902238, 615446200, 0)
    assert counters[1] == PortCounters(2, 1000, 615854972, 5569725891, 0)
    for c in counters[2:]:
        assert (c.rx_bytes, c.tx_bytes) == (0, 0)
    assert all(c.crc_errors == 0 for c in counters)


def test_parse_vlan_mode_off() -> None:
    page_html = {key: load(Path(path).name) for key, path in pages.VLAN_MODE_PAGES.items()}
    assert pages.parse_vlan_mode(page_html) == "off"


def test_parse_vlan_mode_enabled() -> None:
    page_html = {key: load(Path(path).name) for key, path in pages.VLAN_MODE_PAGES.items()}
    page_html["advanced_8021q"] = (
        page_html["advanced_8021q"]
        .replace("value='Disable' name='status' checked/", "value='Disable' name='status' /")
        .replace("value='Enable' name='status' /", "value='Enable' name='status' checked/")
    )
    assert pages.parse_vlan_mode(page_html) == "advanced_8021q"


def test_parse_vlan_membership() -> None:
    assert pages.parse_vlan_membership(load("8021qMembe.cgi")) == (
        (1,),
        VlanMembers(1, ("U",) * 5),
    )


def test_membership_codes() -> None:
    html = load("8021qMembe.cgi").replace('value="11111"', 'value="1203x"')
    _, shown = pages.parse_vlan_membership(html)
    assert shown == VlanMembers(1, ("U", "T", "", "?3", "?x"))


def test_parse_pvids() -> None:
    assert pages.parse_pvids(load("portPVID.cgi")) == tuple((p, 1) for p in range(1, 6))


def test_parse_qos() -> None:
    assert pages.parse_qos(load("qos.cgi"), load("rateLimit.cgi"), load("broadCastFilter.cgi")) == QosConfig(
        "dot1p", tuple(RateLimit(p, None, None) for p in range(1, 6)), False
    )


def test_rate_limit_codes() -> None:
    html = load("rateLimit.cgi")
    first = html.index('<tr class="portID">')
    head, row = html[:first], html[first:]
    row = row.replace('<input type="hidden" value="1">', '<input type="hidden" value="4">', 3)
    qos = pages.parse_qos(load("qos.cgi"), head + row, load("broadCastFilter.cgi"))
    assert qos.rate_limits[0] == RateLimit(4, 2048, 2048)


def test_parse_igmp() -> None:
    assert pages.parse_igmp(load("igmp.cgi")) == IgmpConfig(True, None, False, False, None)


def test_parse_mirror() -> None:
    assert pages.parse_mirror(load("mirror.cgi")) == MirrorConfig(False, None, ())


def test_parse_management() -> None:
    assert pages.parse_management(
        load("plus_utility.cgi"),
        load("ip_source.cgi"),
        load("green_ethernet.cgi"),
        load("loop_detection.cgi"),
    ) == ManagementConfig("web", False, (), False, False)


@pytest.mark.parametrize(
    ("parser", "page"),
    [
        (pages.parse_port_status, "/status.cgi"),
        (pages.parse_pvids, "/portPVID.cgi"),
        (pages.parse_igmp, "/igmp.cgi"),
        (pages.parse_mirror, "/mirror.cgi"),
        (pages.parse_switch_info, "/switch_info.cgi"),
        (pages.parse_vlan_membership, "/8021qMembe.cgi"),
    ],
)
def test_empty_page_raises_page_changed(parser, page: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(pages.PageChanged) as err:
        parser("<html></html>")
    assert err.value.page == page


def test_empty_statistics_raises() -> None:
    with pytest.raises(pages.PageChanged) as err:
        pages.parse_port_statistics("<html></html>", 1)
    assert err.value.page == "/portStatistics.cgi"


def test_management_empty_access_page_raises() -> None:
    with pytest.raises(pages.PageChanged) as err:
        pages.parse_management(
            load("plus_utility.cgi"),
            "<html></html>",
            load("green_ethernet.cgi"),
            load("loop_detection.cgi"),
        )
    assert err.value.page == "/ip_source.cgi"


def test_management_access_entries() -> None:
    # Entry-row markup is hand-written (the real shape is unverified): tr.index rows like the
    # other pages' tr.portID rows, with the address and mask as cell text.
    rows = "".join(
        f'<tr class="index"><td><input type="checkbox" name="index{i}"></td>'
        f'<td sel="text">{ip}</td><td sel="text">{mask}</td></tr>'
        for i, (ip, mask) in enumerate([("192.0.2.10", "255.255.255.255"), ("198.51.100.0", "255.255.255.0")])
    )
    access = load("ip_source.cgi").replace(
        "<input type=hidden name='err_msg'", rows + "<input type=hidden name='err_msg'", 1
    )
    result = pages.parse_management(
        load("plus_utility.cgi"), access, load("green_ethernet.cgi"), load("loop_detection.cgi")
    )
    assert result.access_list == (("192.0.2.10", "255.255.255.255"), ("198.51.100.0", "255.255.255.0"))
