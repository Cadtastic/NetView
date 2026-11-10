"""Linux (and macOS) `ping`, `ip neigh` / `arp -an` and route parsers."""

import re

from netview.application.ports.network import PingResult
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
