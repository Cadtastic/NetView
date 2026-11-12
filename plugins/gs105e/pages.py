"""Parsers for the GS105Ev2 web pages (firmware 1.6.0.11), tested on captured pages.

One small ``HTMLParser`` subclass collects the title, every ``<input>``, every
``<select>`` and the ``tr.portID`` rows; the parsers below read from that result
and raise :class:`PageChanged` when an element they need is missing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .model import (
    IgmpConfig,
    ManagementConfig,
    MirrorConfig,
    PortCounters,
    PortStatus,
    QosConfig,
    RateLimit,
    SwitchInfo,
    VlanMembers,
    VlanMode,
)

LOGIN = "/login.cgi"
LOGOUT = "/logout.cgi"
SWITCH_INFO = "/switch_info.cgi"
PORT_STATUS = "/status.cgi"
PORT_STATISTICS = "/portStatistics.cgi"
VLAN_MODE_PAGES: dict[VlanMode, str] = {
    "basic_8021q": "/8021qBasic.cgi",
    "advanced_8021q": "/8021qCf.cgi",
    "basic_port": "/portBasedBasic.cgi",
    "advanced_port": "/portBasedAdvanced.cgi",
}
VLAN_MEMBERSHIP = "/8021qMembe.cgi"
PVID = "/portPVID.cgi"
QOS = "/qos.cgi"
RATE_LIMIT = "/rateLimit.cgi"
BROADCAST_FILTER = "/broadCastFilter.cgi"
IGMP = "/igmp.cgi"
MIRROR = "/mirror.cgi"
LOOP = "/loop_detection.cgi"
GREEN = "/green_ethernet.cgi"
PLUS_UTILITY = "/plus_utility.cgi"
ACCESS_CONTROL = "/ip_source.cgi"

# The config group's paths, in the order the collector reads them.
CONFIG_PAGES = (
    *VLAN_MODE_PAGES.values(),
    VLAN_MEMBERSHIP,
    PVID,
    QOS,
    RATE_LIMIT,
    BROADCAST_FILTER,
    IGMP,
    MIRROR,
    PLUS_UTILITY,
    ACCESS_CONTROL,
    GREEN,
    LOOP,
)

_SPEED_SETTINGS = {
    "1": "Auto",
    "2": "Disable",
    "3": "10M Half",
    "4": "10M Full",
    "5": "100M Half",
    "6": "100M Full",
}
_LINK_MBPS = {"1000M": 1000, "100M": 100, "10M": 10}
_RATE_KBPS: dict[int, int | None] = {
    1: None,
    2: 512,
    3: 1024,
    4: 2048,
    5: 4096,
    6: 8192,
    7: 16384,
    8: 32768,
    9: 65536,
    10: 131072,
    11: 262144,
    12: 524288,
}
_MEMBER_CODES = {"1": "U", "0": "", "2": "T"}
_ASSET_VERSION = re.compile(r"\?a(\d+(?:\.\d+)+)")
_QUOTES = "'\" "


class PageChanged(Exception):
    """A page no longer has the shape the parser expects."""

    def __init__(self, page: str, reason: str) -> None:
        super().__init__(f"{page}: {reason}")
        self.page = page
        self.reason = reason


@dataclass
class _Cell:
    text: str = ""
    hidden: list[str] = field(default_factory=list)


@dataclass
class _Row:
    cells: list[_Cell] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)


@dataclass
class _Select:
    attrs: dict[str, str | None]
    options: list[tuple[str, bool]] = field(default_factory=list)  # (value, selected)

    @property
    def selected(self) -> str | None:
        for value, selected in self.options:
            if selected:
                return value
        return None


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.inputs: list[dict[str, str | None]] = []
        self.selects: list[_Select] = []
        self.rows: list[_Row] = []
        self.tds: list[_Cell] = []
        self._in_title = False
        self._select: _Select | None = None
        self._option: tuple[str | None, bool] | None = None
        self._option_text = ""
        self._row: _Row | None = None
        self._td_stack: list[_Cell] = []

    def _close_row(self) -> None:
        if self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def _finish_option(self) -> None:
        if self._option is not None and self._select is not None:
            raw, selected = self._option
            value = raw if raw is not None else self._option_text.strip()
            self._select.options.append((value, selected))
        self._option = None
        self._option_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "tr":
            self._close_row()
            if {"portID", "index"} & set((a.get("class") or "").split()):
                self._row = _Row()
        elif tag == "td":
            cell = _Cell()
            self.tds.append(cell)
            self._td_stack.append(cell)
            if self._row is not None:
                self._row.cells.append(cell)
        elif tag == "input":
            self.inputs.append(a)
            if (a.get("type") or "").lower() == "hidden" and self._row is not None:
                value = a.get("value") or ""
                self._row.hidden.append(value)
                if self._td_stack:
                    self._td_stack[-1].hidden.append(value)
        elif tag == "select":
            self._finish_option()
            self._select = _Select(a)
            self.selects.append(self._select)
        elif tag == "option" and self._select is not None:
            self._finish_option()
            self._option = (a.get("value"), "selected" in a)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "td":
            if self._td_stack:
                self._td_stack.pop()
        elif tag in ("tr", "table"):
            self._close_row()
        elif tag == "option":
            self._finish_option()
        elif tag == "select":
            self._finish_option()
            self._select = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._option is not None:
            self._option_text += data
        elif self._td_stack:
            self._td_stack[-1].text += data

    def close(self) -> None:
        super().close()
        self._finish_option()
        self._close_row()


class _Page:
    """Parsed view of one page, with lookups that raise :class:`PageChanged`."""

    def __init__(self, html: str, path: str) -> None:
        self.path = path
        collector = _Collector()
        collector.feed(html)
        collector.close()
        self.title = collector.title.strip()
        self.inputs = collector.inputs
        self.selects = collector.selects
        self.rows = collector.rows
        self.tds = collector.tds

    def fail(self, reason: str) -> PageChanged:
        return PageChanged(self.path, reason)

    def input(self, key: str) -> dict[str, str | None] | None:
        for attrs in self.inputs:
            if attrs.get("id") == key or attrs.get("name") == key:
                return attrs
        return None

    def input_value(self, key: str) -> str:
        attrs = self.input(key)
        if attrs is None:
            raise self.fail(f"missing input {key}")
        return attrs.get("value") or ""

    def select(self, key: str) -> _Select:
        for sel in self.selects:
            if sel.attrs.get("id") == key or sel.attrs.get("name") == key:
                return sel
        raise self.fail(f"missing select {key}")

    def radio(self, name: str) -> str:
        """Value of the checked radio of a group; raises if none is checked."""
        seen = False
        for attrs in self.inputs:
            if (attrs.get("type") or "").lower() == "radio" and attrs.get("name") == name:
                seen = True
                if "checked" in attrs:
                    return attrs.get("value") or ""
        raise self.fail(f"no checked radio {name}" if seen else f"missing radio {name}")

    def port_rows(self) -> list[_Row]:
        rows = [r for r in self.rows if r.hidden]
        if not rows:
            raise self.fail("no port rows")
        return rows

    def label_value(self, label: str) -> str:
        for i, cell in enumerate(self.tds[:-1]):
            if cell.text.strip() == label:
                return self.tds[i + 1].text.strip()
        raise self.fail(f"missing label {label}")


def _to_int(page: _Page, text: str, what: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        raise page.fail(f"{what} is not a number: {text.strip()!r}") from None


def _hidden(page: _Page, row: _Row, cell: int) -> str:
    if len(row.cells) <= cell or not row.cells[cell].hidden:
        raise page.fail(f"port row has no value in column {cell}")
    return row.cells[cell].hidden[0].strip()


def is_login_page(html: str) -> bool:
    """True for the "Redirect to Login" page and for the login form itself."""
    page = _Page(html, LOGIN)
    return page.title == "Redirect to Login" or page.input("rand") is not None


@dataclass(frozen=True, slots=True)
class LoginPage:
    rand: str
    title: str
    firmware: str | None


def parse_login(html: str) -> LoginPage:
    page = _Page(html, LOGIN)
    rand = page.input_value("rand")
    if not rand:
        raise page.fail("empty rand")
    match = _ASSET_VERSION.search(html)
    return LoginPage(rand, page.title, match.group(1) if match else None)


def parse_switch_info(html: str) -> SwitchInfo:
    page = _Page(html, SWITCH_INFO)
    return SwitchInfo(
        product=page.label_value("Product Name"),
        name=page.input_value("switch_name"),
        serial=page.label_value("Serial Number"),
        mac=page.label_value("MAC Address"),
        bootloader=page.label_value("Bootloader Version"),
        firmware=page.label_value("Firmware Version"),
        dhcp=page.select("dhcpMode").selected == "1",
        ip=page.input_value("ip_address"),
        mask=page.input_value("subnet_mask"),
        gateway=page.input_value("gateway_address"),
    )


def _link_mbps(page: _Page, text: str) -> int | None:
    """Linked speed in Mbit/s; ``None`` when the link is down."""
    if text == "No Speed":
        return None
    if text not in _LINK_MBPS:
        raise page.fail(f"unknown linked speed {text!r}")
    return _LINK_MBPS[text]


def _rate_kbps(page: _Page, code: int) -> int | None:
    """Rate limit in kbit/s for a switch rate code; ``None`` means no limit."""
    if code not in _RATE_KBPS:
        raise page.fail(f"unknown rate code {code}")
    return _RATE_KBPS[code]


def parse_port_status(html: str) -> tuple[PortStatus, ...]:
    page = _Page(html, PORT_STATUS)
    result = []
    for row in page.port_rows():
        speed_code = _hidden(page, row, 4)
        result.append(
            PortStatus(
                port=_to_int(page, _hidden(page, row, 1), "port"),
                description=row.cells[2].text.strip(),
                up=_hidden(page, row, 3).lower() == "up",
                speed_setting=_SPEED_SETTINGS.get(speed_code, row.cells[4].text.strip()),
                link_mbps=_link_mbps(page, _hidden(page, row, 5)),
                flow_control=_hidden(page, row, 6) == "1",
                max_mtu=_to_int(page, _hidden(page, row, 7), "max MTU"),
            )
        )
    return tuple(result)


def parse_port_statistics(html: str, t_ms: int) -> tuple[PortCounters, ...]:
    page = _Page(html, PORT_STATISTICS)
    result = []
    for row in page.port_rows():
        if not row.cells or len(row.hidden) < 6:
            raise page.fail("statistics row has too few counters")
        port = _to_int(page, row.cells[0].text, "port")
        v = [_to_int(page, x, "counter") for x in row.hidden[:6]]
        rx, tx, crc = (v[i] * 2**32 + v[i + 1] for i in (0, 2, 4))
        result.append(PortCounters(port, t_ms, rx, tx, crc))
    return tuple(result)


def parse_vlan_mode(page_html: Mapping[str, str]) -> VlanMode:
    found: VlanMode = "off"
    for key, path in VLAN_MODE_PAGES.items():
        if key not in page_html:
            raise PageChanged(path, "page was not read")
        enabled = _Page(page_html[key], path).radio("status") == "Enable"
        if enabled and found == "off":
            found = key
    return found


def parse_vlan_membership(html: str) -> tuple[tuple[int, ...], VlanMembers | None]:
    page = _Page(html, VLAN_MEMBERSHIP)
    select = page.select("VLAN_ID")
    ids = tuple(_to_int(page, v, "VLAN id") for v, _s in select.options if v.strip())
    mem = page.input_value("hiddenMem")
    chosen = select.selected or (select.options[0][0] if select.options else None)
    if chosen is None or not mem:
        return ids, None
    members = tuple(_MEMBER_CODES.get(c, f"?{c}") for c in mem)
    return ids, VlanMembers(_to_int(page, chosen, "VLAN id"), members)


def parse_pvids(html: str) -> tuple[tuple[int, int], ...]:
    page = _Page(html, PVID)
    result = []
    for row in page.port_rows():
        if len(row.cells) < 3:
            raise page.fail("PVID row has too few cells")
        port = _to_int(page, _hidden(page, row, 1), "port")
        result.append((port, _to_int(page, row.cells[2].text, "PVID")))
    return tuple(result)


def parse_qos(qos_html: str, rate_html: str, broadcast_html: str) -> QosConfig:
    qos = _Page(qos_html, QOS)
    rate = _Page(rate_html, RATE_LIMIT)
    broadcast = _Page(broadcast_html, BROADCAST_FILTER)
    limits = []
    for row in rate.port_rows():
        if len(row.hidden) < 3:
            raise rate.fail("rate row has too few values")
        port, ingress, egress = (_to_int(rate, v, "rate value") for v in row.hidden[:3])
        limits.append(RateLimit(port, _rate_kbps(rate, ingress), _rate_kbps(rate, egress)))
    return QosConfig(
        mode="dot1p" if qos.radio("status") == "Enable" else "port",
        rate_limits=tuple(limits),
        storm_control=broadcast.radio("status") == "Enable",
    )


def parse_igmp(html: str) -> IgmpConfig:
    page = _Page(html, IGMP)
    vlan_text = page.input_value("VLAN_ID_ENABLED").strip()
    router = page.select("ROUTER_PORT").selected
    return IgmpConfig(
        enabled=page.radio("status") == "1",
        vlan=_to_int(page, vlan_text, "IGMP VLAN") if vlan_text else None,
        validate_v3_header=page.radio("IP_HEADER") == "1",
        block_unknown=page.radio("BLOCK_UN_MUL_ADDR") == "1",
        router_port=router.strip(_QUOTES) if router is not None else None,
    )


def parse_mirror(html: str) -> MirrorConfig:
    page = _Page(html, MIRROR)
    enabled = (page.select("mirroring").selected or "").strip(_QUOTES) == "0"
    dest_text = (page.select("DestiPort").selected or "").strip(_QUOTES)
    destination = _to_int(page, dest_text, "destination") if dest_text else 0
    members = page.input_value("hiddenMem")
    sources = tuple(i + 1 for i, c in enumerate(members) if c == "1")
    return MirrorConfig(enabled, destination or None, sources)


def parse_management(plus_html: str, access_html: str, green_html: str, loop_html: str) -> ManagementConfig:
    plus = _Page(plus_html, PLUS_UTILITY)
    access = _Page(access_html, ACCESS_CONTROL)
    access.input_value("IPADDRESS")
    access.input_value("NETMASK")
    green = _Page(green_html, GREEN)
    loop = _Page(loop_html, LOOP)
    entries = []
    for row in access.rows:
        texts = [c.text.strip() for c in row.cells if c.text.strip()]
        values = row.hidden if len(row.hidden) >= 2 else texts
        if len(values) >= 2:
            entries.append((values[0], values[1]))
    return ManagementConfig(
        mode="web" if plus.radio("plusUtility") == "1" else "web_and_utility",
        tftp=plus.radio("tftpflag") == "0",
        access_list=tuple(entries),
        power_saving=green.radio("powerSavingMode") == "1",
        loop_detection=loop.radio("loopDetection") == "1",
    )
