"""Helpers shared by the OS-specific network adapters."""

import ipaddress
import locale
import random
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from netview.application.ports.network import PingResult, TcpResult

TIME_RE = re.compile(r"(?:time|zeit|temps|tiempo|tempo)\s*([=<])\s*([\d.,]+)\s*ms", re.IGNORECASE)
TTL_RE = re.compile(r"ttl[=\s]+(\d+)", re.IGNORECASE)
IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
MAC_RE = re.compile(r"\b([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})\b")

_NO_WINDOW = 0x08000000


def valid_ipv4(value: object) -> bool:
    """True only for a dotted-quad IPv4 string; anything else must never reach a command line."""
    if not isinstance(value, str):
        return False
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def valid_ip(value: object) -> bool:
    """True for an IPv4 or IPv6 literal; a host name or anything else must never reach a command line."""
    if not isinstance(value, str):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def is_ipv6(value: str) -> bool:
    return ":" in value


def run(cmd: list[str], timeout: float = 10) -> str:
    """Run a command and return its stdout as text; an empty string on any failure."""
    creationflags = _NO_WINDOW if sys.platform == "win32" else 0
    try:
        done = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    return done.stdout.decode("utf-8", errors="replace")


def run_lines(cmd: list[str], timeout: float, on_line: Callable[[str], None]) -> bool:
    """Run a command and hand each stdout line to on_line as it arrives.

    False if the command could not start or was killed for running past timeout.
    """
    creationflags = _NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except (OSError, ValueError):
        return False
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, kill)
    timer.start()
    encoding = locale.getpreferredencoding(False)
    try:
        if proc.stdout is not None:
            for raw in proc.stdout:
                on_line(raw.decode(encoding, errors="replace").rstrip("\r\n"))
        proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()
    return not timed_out.is_set()


def parse_ping_output(output: str, require_ttl: bool = True) -> PingResult | None:
    """Parse one-echo ping output.

    With require_ttl (IPv4) a reply without a TTL (unreachable, timed out) gives None.
    Without it (IPv6) a reply is a matched time; the TTL is taken when present.
    """
    ttl = TTL_RE.search(output)
    found = TIME_RE.search(output)
    if (require_ttl and not ttl) or (not require_ttl and not found):
        return None
    rtt = 0.0
    if found:
        rtt = float(found.group(2).replace(",", "."))
        if found.group(1) == "<":
            rtt = rtt / 2
    return PingResult(rtt_ms=round(rtt, 2), ttl=int(ttl.group(1)) if ttl else None)


def tcp_probe(ip: str, port: int, timeout_s: float = 1.0) -> TcpResult:
    """Open (with ms), closed (host refused, so it is there) or filtered."""
    started = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout_s):
            return TcpResult("open", round((time.perf_counter() - started) * 1000, 1))
    except ConnectionRefusedError:
        return TcpResult("closed", None)
    except OSError:
        return TcpResult("filtered", None)


def dns_query(server: str, name: str, timeout_s: float = 2.0, port: int = 53) -> float | None:
    """Time one A-record query straight to a DNS server; milliseconds or None."""
    tid = random.randint(0, 0xFFFF)
    try:
        qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.split(".")) + b"\0"
    except UnicodeEncodeError:
        return None
    packet = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", 1, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        started = time.perf_counter()
        deadline = time.monotonic() + timeout_s  # one deadline for the whole exchange
        sock.settimeout(timeout_s)
        sock.connect((server, port))  # a connected socket ignores datagrams from other sources
        sock.send(packet)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            sock.settimeout(remaining)
            data = sock.recv(4096)
            if len(data) >= 4 and struct.unpack(">H", data[:2])[0] == tid:
                break
        elapsed = (time.perf_counter() - started) * 1000
        return round(elapsed, 1) if (data[3] & 0x0F) in (0, 3) else None
    except OSError:
        return None
    finally:
        sock.close()


def local_ip() -> str:
    """The address of the interface that routes to the internet (no packet is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 53))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
