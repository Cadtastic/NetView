"""Collector tests: the page reads that feed the poll groups."""

from __future__ import annotations

from pathlib import Path

from netview_local_plugins.gs105e import pages
from netview_local_plugins.gs105e.client import SwitchSession
from netview_local_plugins.gs105e.collector import read_config, read_counters, read_status
from netview_local_plugins.gs105e.model import VlanConfig
from netview_local_plugins.gs105e.tools.fake_switch import FakeSwitch

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fw-1.6.0.11"


def load(name: str) -> str:
    return (FIX / name).read_bytes().decode("utf-8", errors="replace")


def logged_in() -> tuple[SwitchSession, FakeSwitch]:
    fake = FakeSwitch(FIX)
    session = SwitchSession("sw", 80, "secret", fake, gap_s=0.0)
    session.login()
    fake.requests.clear()
    return session, fake


def test_read_counters_matches_the_parser() -> None:
    session, fake = logged_in()
    assert read_counters(session, 1234) == pages.parse_port_statistics(load("portStatistics.cgi"), 1234)
    assert fake.requests == [("GET", pages.PORT_STATISTICS)]


def test_read_status() -> None:
    session, fake = logged_in()
    snap = read_status(session, 99)
    assert snap.t_ms == 99
    assert snap.groups == {"status"}
    assert snap.ports == pages.parse_port_status(load("status.cgi"))
    assert snap.info is None
    assert fake.requests == [("GET", pages.PORT_STATUS)]


def test_read_config_matches_the_parsers_and_reads_each_page_once() -> None:
    session, fake = logged_in()
    snap = read_config(session, 7)
    assert snap.groups == {"config"}
    assert snap.t_ms == 7
    assert snap.ports == ()
    assert snap.info == pages.parse_switch_info(load("switch_info.cgi"))
    ids, shown = pages.parse_vlan_membership(load("8021qMembe.cgi"))
    mode = pages.parse_vlan_mode({k: load(p.lstrip("/")) for k, p in pages.VLAN_MODE_PAGES.items()})
    assert snap.vlans == VlanConfig(mode, ids, shown, pages.parse_pvids(load("portPVID.cgi")))
    assert snap.qos == pages.parse_qos(load("qos.cgi"), load("rateLimit.cgi"), load("broadCastFilter.cgi"))
    assert snap.igmp == pages.parse_igmp(load("igmp.cgi"))
    assert snap.mirror == pages.parse_mirror(load("mirror.cgi"))
    assert snap.management == pages.parse_management(
        load("plus_utility.cgi"),
        load("ip_source.cgi"),
        load("green_ethernet.cgi"),
        load("loop_detection.cgi"),
    )
    asked = [path for _, path in fake.requests]
    assert asked == [pages.SWITCH_INFO, *pages.CONFIG_PAGES]
    assert len(set(asked)) == len(asked)
