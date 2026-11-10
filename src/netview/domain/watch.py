"""Watches: an IP with optional ports and label."""

import ipaddress
from dataclasses import dataclass

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
