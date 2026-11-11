"""Linux (and macOS) `ping`, `ip neigh` / `arp -an`, route, `/proc/net/dev`, `ss` and `nmcli` parsers."""

import re

from netview.application.ports.network import PingResult
from netview.application.ports.system import TcpSocket, WifiInfo
from netview.domain.keys import norm_mac
from netview.infrastructure.net.common import IPV4_RE, MAC_RE, parse_ping_output

NEIGH_COMMAND = ["ip", "-4", "neigh"]
ARP_COMMAND = ["arp", "-an"]
ROUTE_COMMAND = ["ip", "-4", "route", "show", "default"]
MACOS_ROUTE_COMMAND = ["route", "-n", "get", "default"]


def ping_command(ip: str, timeout_ms: int) -> list[str]:
    # Linux ping -W takes whole seconds.
    return ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), ip]


def macos_ping_command(ip: str, timeout_ms: int) -> list[str]:
    return ["ping", "-c", "1", "-W", str(timeout_ms), ip]


def parse_ping(output: str) -> PingResult | None:
    return parse_ping_output(output)


def parse_arp(output: str) -> dict[str, str]:
    """Resolved entries from `ip -4 neigh` or `arp -an`; FAILED and INCOMPLETE are skipped."""
    table: dict[str, str] = {}
    for line in output.splitlines():
        if "FAILED" in line or "INCOMPLETE" in line.upper():
            continue
        ip, mac = IPV4_RE.search(line), MAC_RE.search(line)
        if ip and mac:
            normal = norm_mac(mac.group(1))
            if normal:
                table[ip.group(1)] = normal
    return table


def parse_default_gateway(output: str, local_ip: str) -> str | None:
    """Handles `ip route` ("default via X") and macOS `route -n get default` ("gateway: X")."""
    found = re.search(r"default via (\S+)", output) or re.search(r"gateway:\s*(\S+)", output)
    return found.group(1) if found else None


SS_COMMAND = ["ss", "-tanpH", "-4"]
MACOS_NETSTAT_COMMAND = ["netstat", "-anp", "tcp"]
NMCLI_COMMAND = ["nmcli", "-t", "-f", "active,ssid,signal,chan,rate", "dev", "wifi"]


def parse_proc_net_dev(text: str) -> tuple[int, int] | None:
    """Total (rx, tx) bytes of every interface except ``lo``."""
    rx = tx = 0
    try:
        for line in text.splitlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip() == "lo":
                continue
            values = data.split()
            rx, tx = rx + int(values[0]), tx + int(values[8])
    except (ValueError, IndexError):
        return None
    return rx, tx


def _port(text: str) -> int:
    return int(text) if text.isdigit() else 0


def parse_ss(output: str, own_pid: int) -> list[TcpSocket]:
    """Rows of `ss -tanpH -4`; rows owned by ``own_pid`` are dropped, the process name is kept."""
    rows: list[TcpSocket] = []
    own = re.compile(rf"pid={own_pid}\b")
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5 or ":" not in fields[3] or ":" not in fields[4] or own.search(line):
            continue
        local_ip, local_port = fields[3].rsplit(":", 1)
        remote_ip, remote_port = fields[4].rsplit(":", 1)
        proc = re.search(r'"([^"]+)"', line)
        process = proc.group(1) if proc else ""
        rows.append(TcpSocket(local_ip, _port(local_port), remote_ip, _port(remote_port), fields[0], process))
    return rows


_MACOS_ROW = re.compile(r"^tcp4\s+\d+\s+\d+\s+(\S+)\.(\d+|\*)\s+(\S+)\.(\d+|\*)\s+(\S+)")


def parse_netstat_macos(output: str) -> list[TcpSocket]:
    """Rows of macOS `netstat -anp tcp`; it reports no process."""
    rows: list[TcpSocket] = []
    for line in output.splitlines():
        m = _MACOS_ROW.match(line)
        if m:
            rows.append(TcpSocket(m[1], _port(m[2]), m[3], _port(m[4]), m[5], ""))
    return rows


def _nmcli_fields(line: str) -> list[str]:
    """Split a terse nmcli line on colons that are not escaped with a backslash."""
    parts = re.split(r"(?<!\\):", line)
    return [re.sub(r"\\(.)", r"\1", part) for part in parts]


def parse_nmcli(output: str) -> WifiInfo | None:
    """The active access point of `nmcli -t -f active,ssid,signal,chan,rate dev wifi`."""
    for line in output.splitlines():
        fields = _nmcli_fields(line)
        if len(fields) >= 5 and fields[0] == "yes":
            rate = re.search(r"\d+(?:\.\d+)?", fields[4])
            return WifiInfo(
                ssid=fields[1],
                signal_pct=int(fields[2]) if fields[2].isdigit() else None,
                channel=fields[3],
                rx_rate_mbps=float(rate.group(0)) if rate else None,
                state="connected",
            )
    return None
