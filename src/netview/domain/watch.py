"""Watches: an IP with optional ports and label."""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from netview.domain.errors import ValidationError

_MAX_PORTS = 16
_MAX_LABEL = 60


@dataclass(frozen=True)
class Watch:
    ip: str
    ports: tuple[int, ...] = ()
    label: str = ""

    def spec(self) -> str:
        s = self.ip
        if self.ports:
            s += ":" + ",".join(str(p) for p in self.ports)
        if self.label:
            s += "=" + self.label
        return s


def parse_watch_spec(spec: str) -> Watch:
    """Parse ``IP[:P1,P2][=LABEL]``. Port order is kept, duplicates dropped."""
    rest, _, label = spec.partition("=")
    ip_part, _, port_part = rest.partition(":")
    try:
        ip = str(ipaddress.IPv4Address(ip_part.strip()))
    except ValueError as exc:
        raise ValidationError(f"invalid IP address: {ip_part.strip()!r}") from exc
    ports: list[int] = []
    for raw in port_part.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            port = int(raw)
        except ValueError as exc:
            raise ValidationError(f"invalid port: {raw!r}") from exc
        if not 1 <= port <= 65535:
            raise ValidationError(f"port out of range: {port}")
        if port not in ports:
            ports.append(port)
    return Watch(ip, tuple(ports[:_MAX_PORTS]), label.strip()[:_MAX_LABEL])


class WatchState(StrEnum):
    PENDING = "pending"
    UP = "up"
    DEGRADED = "degraded"
    PRESENT = "present"
    ABSENT = "absent"
    DOWN = "down"


WATCH_LABELS: Mapping[WatchState, str] = {
    WatchState.PENDING: "checking",
    WatchState.UP: "up",
    WatchState.DEGRADED: "partly up",
    WatchState.PRESENT: "on the network only",
    WatchState.ABSENT: "not on the network",
    WatchState.DOWN: "not replying",
}


@dataclass(frozen=True)
class WatchProbe:
    """What a health provider measured for one watch: ping, ARP and a TCP probe per watched port."""

    ip: str
    checked_ms: int
    on_subnet: bool
    l2: bool | None
    mac: str | None
    rtt_ms: float | None
    ports: Mapping[int, Literal["open", "closed", "filtered"]]


@dataclass(frozen=True)
class WatchStatus:
    ip: str
    label: str
    ports: tuple[int, ...]
    state: WatchState
    since_ms: int | None
    checked_ms: int | None
    on_subnet: bool
    l2: bool | None
    mac: str | None
    rtt_ms: float | None
    port_state: Mapping[int, str]
    diagnosis: str
    history: tuple[float, ...]


_ABSENT_DIAGNOSIS = (
    "No reply even at the hardware level (ARP): the device isn't on this network segment. Check its "
    "cable and the link lights at both ends, which port it is plugged into (a management controller "
    "such as iDRAC/iLO may be set to its dedicated port or a shared LOM port), the switch VLAN on that "
    "port, and that its address and mask match this subnet."
)


def assess_watch(watch: Watch, probe: WatchProbe) -> tuple[WatchState, str]:
    """Decide a watch's state and explain it. Ported from the old LAN monitor's ``check_watch``."""
    open_ = [p for p in watch.ports if probe.ports.get(p) == "open"]
    refused = [p for p in watch.ports if probe.ports.get(p) == "closed"]
    replied = probe.rtt_ms is not None
    present = replied or bool(open_) or bool(refused) or bool(probe.l2)
    if watch.ports and len(open_) == len(watch.ports):
        return WatchState.UP, "Reachable: every watched port answers."
    if not watch.ports and replied:
        return WatchState.UP, "Reachable: answers ping."
    if open_ or refused or replied:
        closed = [p for p in watch.ports if p not in open_]
        return WatchState.DEGRADED, (
            f"Host answers, but port {', '.join(map(str, closed))} "
            f"{'is' if len(closed) == 1 else 'are'} not open. The service may be off, "
            "on another port, or still starting."
        )
    if present:
        return WatchState.PRESENT, (
            "Answers ARP, so it is on this network, but not ping or the watched ports. "
            "A firewall may be blocking them, or the service is off."
        )
    if probe.on_subnet:
        return WatchState.ABSENT, _ABSENT_DIAGNOSIS
    return WatchState.DOWN, (
        "No reply. This address is outside the local subnet, so the gateway must route to it."
    )
