"""Helpers shared by the OS-specific network adapters."""

import ipaddress
import random
import re
import socket
import struct
import subprocess
import sys
import time

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


def parse_ping_output(output: str) -> PingResult | None:
    """Parse one-echo ping output. A reply without a TTL (unreachable, timed out) gives None."""
    ttl = TTL_RE.search(output)
    if not ttl:
        return None
    rtt = 0.0
    found = TIME_RE.search(output)
    if found:
        rtt = float(found.group(2).replace(",", "."))
        if found.group(1) == "<":
            rtt = rtt / 2
    return PingResult(rtt_ms=round(rtt, 2), ttl=int(ttl.group(1)))


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
