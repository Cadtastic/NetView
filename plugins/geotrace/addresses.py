"""Address helpers: resolve what the user typed, classify hop IPs, validate input."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from typing import Any, Literal

AddressClass = Literal["public", "private", "cgnat", "none"]
Family = Literal["ipv4", "ipv6"]

_CGNAT = ipaddress.IPv4Network("100.64.0.0/10")
_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
)
_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

# "Not found" style codes. On Windows EAI_NODATA and EAI_NONAME are the same number
# (11001) and on Linux a host with only the other family can give either, so none of
# them proves anything alone: resolve() asks again without a family to tell them apart.
_NOT_FOUND_CODES = frozenset(
    code
    for code in (getattr(socket, name, None) for name in ("EAI_NONAME", "EAI_NODATA", "EAI_ADDRFAMILY"))
    if code is not None
)


class ResolveError(Exception):
    """The address could not be turned into an IP of the wanted family."""


def _parse(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if "%" in text:  # scoped literals (fe80::1%eth0) are not plain addresses
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def family_of(ip: str) -> Family:
    return "ipv6" if ":" in ip else "ipv4"


def classify(ip: str) -> AddressClass:
    address = _parse(ip)
    if address is None:
        return "none"
    if isinstance(address, ipaddress.IPv4Address) and address in _CGNAT:
        return "cgnat"
    if any(address.version == net.version and address in net for net in _PRIVATE_NETWORKS):
        return "private"
    return "public"


def valid_address(text: str) -> bool:
    if _parse(text) is not None:
        return True
    if not 1 <= len(text) <= 253:
        return False
    return all(_LABEL.fullmatch(label) for label in text.split("."))


def resolve(
    address: str,
    family: str,
    getaddrinfo: Callable[..., Any] = socket.getaddrinfo,
) -> str:
    """Return the IP to trace. A literal returns itself (its own family wins)."""
    if _parse(address) is not None:
        return address
    wanted = socket.AF_INET6 if family == "ipv6" else socket.AF_INET
    label = "IPv6" if family == "ipv6" else "IPv4"
    no_family = ResolveError(f"{address} has no {label} address")
    try:
        results = getaddrinfo(address, None, wanted, socket.SOCK_STREAM)
    except (socket.gaierror, OSError, UnicodeError) as error:
        if (
            isinstance(error, socket.gaierror)
            and error.errno in _NOT_FOUND_CODES
            and _exists_in_some_family(address, getaddrinfo)
        ):
            raise no_family from error
        raise ResolveError(f"cannot find {address}") from error
    if not results:
        raise no_family
    return str(results[0][4][0])


def _exists_in_some_family(address: str, getaddrinfo: Callable[..., Any]) -> bool:
    try:
        return bool(getaddrinfo(address, None, socket.AF_UNSPEC, socket.SOCK_STREAM))
    except (OSError, UnicodeError):
        return False
