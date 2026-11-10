"""NetworkTools adapter backed by the operating system's own commands."""

import shutil
import socket
import sys

from netview.application.ports.network import PingResult, TcpResult
from netview.infrastructure.net import common, linux, windows


class SystemNetworkTools:
    """Implements NetworkTools. Never raises: failures give None or an empty table."""

    def __init__(self, platform: str = sys.platform) -> None:
        self._win = platform == "win32"
        self._mac = platform == "darwin"

    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
        if self._win:
            command = windows.ping_command(ip, timeout_ms)
        elif self._mac:
            command = linux.macos_ping_command(ip, timeout_ms)
        else:
            command = linux.ping_command(ip, timeout_ms)
        output = common.run(command, timeout=timeout_ms / 1000 + 3)
        return windows.parse_ping(output) if self._win else linux.parse_ping(output)

    def arp_table(self) -> dict[str, str]:
        if self._win:
            return windows.parse_arp(common.run(windows.ARP_COMMAND))
        if not self._mac and shutil.which("ip"):
            return linux.parse_arp(common.run(linux.NEIGH_COMMAND))
        return linux.parse_arp(common.run(linux.ARP_COMMAND))

    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult:
        return common.tcp_probe(ip, port, timeout_s)

    def dns_query(self, server: str, name: str, timeout_s: float = 2.0) -> float | None:
        return common.dns_query(server, name, timeout_s)

    def local_ip(self) -> str:
        return common.local_ip()

    def default_gateway(self, local_ip: str) -> str | None:
        if self._win:
            return windows.parse_default_gateway(common.run(windows.ROUTE_COMMAND), local_ip)
        command = linux.MACOS_ROUTE_COMMAND if self._mac else linux.ROUTE_COMMAND
        return linux.parse_default_gateway(common.run(command), local_ip)

    def hostname(self) -> str:
        try:
            return socket.gethostname()
        except OSError:
            return ""
