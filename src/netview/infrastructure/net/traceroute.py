"""Traceroute commands and line parsers. Numbers and IPs only; words in any language are ignored."""

import ipaddress
import re
from collections.abc import Sequence

from netview.application.ports.network import TraceHop
from netview.infrastructure.net.common import is_ipv6
from netview.infrastructure.net.windows import system_exe

MAX_HOPS = 64
PROBES = 3

# One probe: "<1 ms", "30 ms", "0.512 ms", "0.412ms" or "*". Not part of a longer token (IPs, "!H").
_PROBE_RE = re.compile(r"(?<![\w.:])(?:(<)?\s*(\d+(?:[.,]\d+)?)\s*ms|\*)(?![\w.:])")
_HOP_RE = re.compile(r"^\s*(\d+)(?:\s+(.*))?$")
_TRACEPATH_RE = re.compile(r"^\s*(\d+):\s+(.*)$")


def clamp_hops(max_hops: int) -> int:
    return max(1, min(MAX_HOPS, max_hops))


def clamp_timeout_ms(probe_timeout_ms: int) -> int:
    return max(100, min(5000, probe_timeout_ms))


def run_timeout(max_hops: int, probe_timeout_ms: int) -> float:
    """Seconds allowed for a whole run: every hop answering three probes at the timeout, plus slack."""
    return max_hops * PROBES * probe_timeout_ms / 1000 + 10


def windows_command(ip: str, max_hops: int, timeout_ms: int) -> list[str]:
    family = "-6" if is_ipv6(ip) else "-4"
    return [
        system_exe("TRACERT.EXE"),
        "-d",
        "-h",
        str(clamp_hops(max_hops)),
        "-w",
        str(clamp_timeout_ms(timeout_ms)),
        family,
        ip,
    ]


def linux_command(ip: str, max_hops: int, timeout_ms: int) -> list[str]:
    seconds = max(1, round(clamp_timeout_ms(timeout_ms) / 1000))
    family = ["-6"] if is_ipv6(ip) else []
    return ["traceroute", "-n", "-m", str(clamp_hops(max_hops)), "-w", str(seconds), "-q", "3", *family, ip]


def tracepath_command(ip: str, max_hops: int) -> list[str]:
    family = ["-6"] if is_ipv6(ip) else []
    return ["tracepath", "-n", "-m", str(clamp_hops(max_hops)), *family, ip]


def _first_ip(text: str) -> str | None:
    for token in text.split():
        candidate = token.strip("()[]")
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return candidate
    return None


def _rtts(text: str) -> tuple[float | None, ...]:
    found: list[float | None] = []
    for m in _PROBE_RE.finditer(text):
        if m.group(2) is None:
            found.append(None)
        elif m.group(1):  # "<1 ms": under a millisecond, recorded as half, like parse_ping_output
            found.append(float(m.group(2).replace(",", ".")) / 2)
        else:
            found.append(float(m.group(2).replace(",", ".")))
    return tuple(found[:PROBES])


def _hop(line: str) -> TraceHop | None:
    m = _HOP_RE.match(line)
    if m is None:
        return None
    rest = m.group(2) or ""
    return TraceHop(int(m.group(1)), _first_ip(rest), _rtts(rest))


def parse_windows_line(line: str) -> TraceHop | None:
    """A tracert row. An error row ("Transmit error: code 1231.") is a hop with no IP and no RTTs."""
    return _hop(line)


def parse_traceroute_line(line: str) -> TraceHop | None:
    """A Linux traceroute row: the first IP wins when probes were answered by several routers."""
    return _hop(line)


def parse_tracepath_line(line: str) -> TraceHop | None:
    """A tracepath row. One RTT per row; the caller keeps the best per hop number."""
    if "[LOCALHOST]" in line:
        return None
    m = _TRACEPATH_RE.match(line)
    if m is None:
        return None
    rest = m.group(2)
    ip = _first_ip(rest)
    rtts = _rtts(rest)[:1]
    return TraceHop(int(m.group(1)), ip, rtts or (None,))


def merge_best(first: TraceHop, other: TraceHop) -> TraceHop:
    """Two tracepath rows for one hop number: keep the lower RTT (and an IP if either has one)."""
    times = [r for r in (*first.rtts_ms, *other.rtts_ms) if r is not None]
    return TraceHop(first.n, first.ip or other.ip, (min(times),) if times else first.rtts_ms)


def reached(target: str, hops: Sequence[TraceHop]) -> bool:
    if not hops or hops[-1].ip is None:
        return False
    try:
        return ipaddress.ip_address(hops[-1].ip) == ipaddress.ip_address(target)
    except ValueError:
        return False
