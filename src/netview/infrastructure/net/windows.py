"""Windows `ping`, `arp -a` and `route print` parsers."""

from netview.application.ports.network import PingResult
from netview.domain.keys import norm_mac
from netview.infrastructure.net.common import IPV4_RE, MAC_RE, parse_ping_output

ROUTE_COMMAND = ["route", "print", "-4", "0.0.0.0"]
ARP_COMMAND = ["arp", "-a"]


def ping_command(ip: str, timeout_ms: int) -> list[str]:
    return ["ping", "-n", "1", "-w", str(timeout_ms), ip]


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
