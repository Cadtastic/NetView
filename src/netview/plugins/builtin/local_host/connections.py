"""Summarise this device's TCP sockets (ported from LM 1488-1529)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from ipaddress import AddressValueError, IPv4Address, IPv4Network
from typing import Any

from netview.sdk import TcpSocket

COMMON_PORTS = [  # LM 100-106
    (22, "SSH"), (23, "Telnet"), (53, "DNS"), (80, "HTTP"), (139, "NetBIOS"),
    (443, "HTTPS"), (445, "SMB"), (554, "RTSP"), (631, "IPP"), (1883, "MQTT"),
    (3389, "RDP"), (5000, "UPnP/NAS"), (5900, "VNC"), (8006, "Proxmox"),
    (8008, "Cast"), (8060, "Roku"), (8080, "HTTP-alt"), (8443, "HTTPS-alt"),
    (9100, "Printer"),
]  # fmt: skip
PORT_NAMES = dict(COMMON_PORTS)

LISTENING_LIMIT = 60  # LM 1524-1526
ESTABLISHED_LIMIT = 40
TRYING_LIMIT = 20

_CGNAT = IPv4Network("100.64.0.0/10")

Key = tuple[str, str, int]  # process, remote address, remote port


def scope_of(ip: str, subnet: IPv4Network) -> str:
    """``lan``, ``private`` (private or carrier-grade NAT), ``internet``, or ``other`` for a non-IPv4 text."""
    try:
        addr = IPv4Address(ip)
    except (AddressValueError, ValueError):
        return "other"
    if addr in subnet:
        return "lan"
    return "private" if addr.is_private or addr in _CGNAT else "internet"


def _rows(
    counter: Counter[Key], limit: int, subnet: IPv4Network, name_for: Callable[[str], str]
) -> list[dict[str, Any]]:
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0][1], kv[0][2]))[:limit]
    return [
        {
            "process": process or "",
            "remote": remote,
            "port": port,
            "service": PORT_NAMES.get(port, ""),
            "count": count,
            "scope": scope_of(remote, subnet),
            "name": name_for(remote),
        }
        for (process, remote, port), count in ordered
    ]


def summarize(
    sockets: Iterable[TcpSocket], subnet: IPv4Network, name_for: Callable[[str], str]
) -> dict[str, Any]:
    """The connections card's data.

    Listening sockets are listed by port; established ones are grouped by process, remote address and
    port; ``SYN*`` sockets are the ones still trying to connect. Loopback and unspecified remotes are skipped.
    """
    rows = list(sockets)
    states = Counter(r.state for r in rows)
    listening: dict[tuple[int, str], str] = {}
    established: Counter[Key] = Counter()
    trying: Counter[Key] = Counter()
    for r in rows:
        state = r.state.upper()
        if state.startswith("LISTEN"):
            listening[(r.local_port, r.local_ip)] = r.process
            continue
        if r.remote_ip.startswith("127.") or r.remote_ip in ("0.0.0.0", "*"):
            continue
        key = (r.process, r.remote_ip, r.remote_port)
        if state in ("ESTABLISHED", "ESTAB"):
            established[key] += 1
        elif state.startswith("SYN"):
            trying[key] += 1
    return {
        "total": len(rows),
        "states": dict(sorted(states.items(), key=lambda kv: -kv[1])),
        "listening": [
            {"port": port, "addr": addr, "process": process or ""}
            for (port, addr), process in sorted(listening.items())
        ][:LISTENING_LIMIT],
        "remotes": _rows(established, ESTABLISHED_LIMIT, subnet, name_for),
        "trying": _rows(trying, TRYING_LIMIT, subnet, name_for),
        "unique_remotes": len({k[1] for k in established}),
        "lan_conns": sum(n for k, n in established.items() if scope_of(k[1], subnet) == "lan"),
    }
