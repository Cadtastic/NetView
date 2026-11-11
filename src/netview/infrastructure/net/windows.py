"""Windows `ping`, `arp -a`, `route print`, `netstat`, `tasklist` and `netsh wlan` commands and parsers."""

import csv
import os
import re

from netview.application.ports.network import PingResult
from netview.application.ports.system import TcpSocket, WifiInfo
from netview.domain.keys import norm_mac
from netview.infrastructure.net.common import IPV4_RE, MAC_RE, parse_ping_output


def system_exe(name: str) -> str:
    """Absolute path of a System32 tool, so CreateProcess never searches the current directory."""
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", name)  # noqa: SIM112


def route_command() -> list[str]:
    return [system_exe("ROUTE.EXE"), "print", "-4", "0.0.0.0"]


def arp_command() -> list[str]:
    return [system_exe("ARP.EXE"), "-a"]


def ping_command(ip: str, timeout_ms: int) -> list[str]:
    return [system_exe("PING.EXE"), "-n", "1", "-w", str(timeout_ms), ip]


def parse_ping(output: str) -> PingResult | None:
    return parse_ping_output(output)


def parse_arp(output: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for line in output.splitlines():
        ip, mac = IPV4_RE.search(line), MAC_RE.search(line)
        if ip and mac:
            normal = norm_mac(mac.group(1))
            if normal:
                table[ip.group(1)] = normal
    return table


def parse_default_gateway(output: str, local_ip: str) -> str | None:
    """Pick the 0.0.0.0 route on the local interface, then the lowest metric."""
    best: tuple[tuple[int, int], str] | None = None
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0] == "0.0.0.0" and fields[1] == "0.0.0.0":
            metric = int(fields[4]) if fields[4].isdigit() else 9999
            score = (0 if fields[3] == local_ip else 1, metric)
            if best is None or score < best[0]:
                best = (score, fields[2])
    return best[1] if best else None


def netstat_e_command() -> list[str]:
    return [system_exe("NETSTAT.EXE"), "-e"]


def netstat_ano_command() -> list[str]:
    return [system_exe("NETSTAT.EXE"), "-ano", "-p", "tcp"]


def tasklist_command() -> list[str]:
    return [system_exe("TASKLIST.EXE"), "/fo", "csv", "/nh"]


def netsh_wlan_command() -> list[str]:
    return [system_exe("NETSH.EXE"), "wlan", "show", "interfaces"]


def parse_netstat_e(output: str) -> tuple[int, int] | None:
    """The ``Bytes`` row of `netstat -e`: total (received, sent) across adapters."""
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0].lower() == "bytes" and fields[1].isdigit() and fields[2].isdigit():
            return int(fields[1]), int(fields[2])
    return None


_NETSTAT_ROW = re.compile(r"^\s*TCP\s+(\S+):(\d+)\s+(\S+):(\d+)\s+(\S+)\s+(\d+)\s*$")


def parse_netstat_ano(output: str, own_pid: int) -> list[TcpSocket]:
    """TCP rows of `netstat -ano -p tcp`, minus our own PID. ``process`` holds the PID text for now."""
    rows: list[TcpSocket] = []
    for line in output.splitlines():
        m = _NETSTAT_ROW.match(line)
        if m and m[6] != str(own_pid):
            rows.append(TcpSocket(m[1], int(m[2]), m[3], int(m[4]), m[5], m[6]))
    return rows


def parse_tasklist(output: str) -> dict[str, str]:
    """PID -> image name from `tasklist /fo csv /nh`."""
    names: dict[str, str] = {}
    for row in csv.reader(output.splitlines()):
        if len(row) >= 2 and row[1].isdigit():
            names[row[1]] = row[0]
    return names


_WLAN_KEYS = {
    "ssid": "ssid",
    "ap bssid": "bssid",
    "bssid": "bssid",
    "signal": "signal",
    "radio type": "radio",
    "band": "band",
    "channel": "channel",
    "receive rate (mbps)": "rx",
    "transmit rate (mbps)": "tx",
    "state": "state",
    "authentication": "auth",
}


def _mbps(text: str | None) -> float | None:
    found = re.search(r"\d+(?:[.,]\d+)?", text or "")
    return float(found.group(0).replace(",", ".")) if found else None


def parse_netsh_wlan(output: str) -> WifiInfo | None:
    """The first interface of `netsh wlan show interfaces`; ``None`` unless it is connected."""
    info: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        mapped = _WLAN_KEYS.get(key.strip().lower())
        if mapped and mapped not in info:
            info[mapped] = value.strip()
    if info.get("state", "").lower() != "connected":
        return None
    digits = re.sub(r"\D", "", info.get("signal", ""))
    return WifiInfo(
        ssid=info.get("ssid", ""),
        bssid=info.get("bssid", ""),
        signal_pct=int(digits) if digits else None,
        radio=info.get("radio", ""),
        band=info.get("band", ""),
        channel=info.get("channel", ""),
        rx_rate_mbps=_mbps(info.get("rx")),
        tx_rate_mbps=_mbps(info.get("tx")),
        state=info["state"],
        auth=info.get("auth", ""),
    )
