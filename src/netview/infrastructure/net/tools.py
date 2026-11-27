"""NetworkTools adapter backed by the operating system's own commands."""

import shutil
import socket
import sys
from collections.abc import Callable

from netview.application.ports.network import PingResult, TcpResult, TraceHop, TraceResult
from netview.infrastructure.net import common, linux, traceroute, windows


class SystemNetworkTools:
    """Implements NetworkTools. Never raises: failures give None or an empty table.

    The one exception: an exception raised by a traceroute ``on_hop`` callback propagates to the caller,
    after the child process has been cleaned up.
    """

    def __init__(self, platform: str = sys.platform) -> None:
        self._win = platform == "win32"
        self._mac = platform == "darwin"

    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None:
        if not common.valid_ip(ip):
            return None
        require_ttl = not common.is_ipv6(ip)
        if self._win:
            command = windows.ping_command(ip, timeout_ms)
        elif self._mac:
            command = linux.macos_ping_command(ip, timeout_ms)
        else:
            command = linux.ping_command(ip, timeout_ms)
        timeout = timeout_ms / 1000 + 3
        output = common.run(command, timeout=timeout)
        if not output and not require_ttl and not self._win and not self._mac:
            # `ping -6` unsupported (usage goes to stderr); a real timeout still prints statistics.
            output = common.run(linux.ping6_command(ip, timeout_ms), timeout=timeout)
        parse = windows.parse_ping if self._win else linux.parse_ping
        return parse(output, require_ttl)

    def arp_table(self) -> dict[str, str]:
        if self._win:
            return windows.parse_arp(common.run(windows.arp_command()))
        if not self._mac and shutil.which("ip"):
            return linux.parse_arp(common.run(linux.NEIGH_COMMAND))
        return linux.parse_arp(common.run(linux.ARP_COMMAND))

    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult:
        if not common.valid_ipv4(ip):
            return TcpResult("filtered", None)
        return common.tcp_probe(ip, port, timeout_s)

    def dns_query(self, server: str, name: str, timeout_s: float = 2.0) -> float | None:
        if not common.valid_ipv4(server):
            return None
        return common.dns_query(server, name, timeout_s)

    def traceroute(
        self,
        ip: str,
        max_hops: int = 30,
        probe_timeout_ms: int = 1000,
        on_hop: Callable[[TraceHop], None] | None = None,
    ) -> TraceResult:
        if not common.valid_ip(ip):
            return TraceResult(ip, (), False, "not an IP address")
        hops_limit = traceroute.clamp_hops(max_hops)
        timeout_ms = traceroute.clamp_timeout_ms(probe_timeout_ms)
        if self._win:
            command = traceroute.windows_command(ip, hops_limit, timeout_ms)
            parse = traceroute.parse_windows_line
            merge = False
        elif shutil.which("traceroute"):
            command = traceroute.linux_command(ip, hops_limit, timeout_ms)
            parse = traceroute.parse_traceroute_line
            merge = False
        elif shutil.which("tracepath"):
            command = traceroute.tracepath_command(ip, hops_limit)
            parse = traceroute.parse_tracepath_line
            merge = True
        else:
            return TraceResult(ip, (), False, "traceroute is not installed")

        hops: list[TraceHop] = []
        pending: list[TraceHop] = []  # tracepath: the hop still collecting rows with the same number

        def emit(hop: TraceHop) -> None:
            hops.append(hop)
            if on_hop is not None:
                on_hop(hop)

        def on_line(line: str) -> None:
            hop = parse(line)
            if hop is None:
                return
            if not merge:
                emit(hop)
            elif pending and pending[0].n == hop.n:
                pending[0] = traceroute.merge_best(pending[0], hop)
            else:
                if pending:
                    emit(pending.pop())
                pending.append(hop)

        finished = common.run_lines(command, traceroute.run_timeout(hops_limit, timeout_ms), on_line)
        if pending:
            emit(pending.pop())
        error = None
        if not finished:
            error = "timed out" if hops else "traceroute could not be run"
        elif not any(h.ip is not None and any(r is not None for r in h.rtts_ms) for h in hops):
            error = "no route to the target"
        return TraceResult(ip, tuple(hops), traceroute.reached(ip, hops), error)

    def local_ip(self) -> str:
        return common.local_ip()

    def default_gateway(self, local_ip: str) -> str | None:
        if not common.valid_ipv4(local_ip):
            return None
        if self._win:
            return windows.parse_default_gateway(common.run(windows.route_command()), local_ip)
        command = linux.MACOS_ROUTE_COMMAND if self._mac else linux.ROUTE_COMMAND
        return linux.parse_default_gateway(common.run(command), local_ip)

    def hostname(self) -> str:
        try:
            return socket.gethostname()
        except OSError:
            return ""
