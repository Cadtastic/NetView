"""The address rule: only private IPv4 addresses may be saved or contacted."""

from __future__ import annotations

import ipaddress

_PRIVATE_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def is_allowed_ip(ip: str) -> bool:
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return any(address in net for net in _PRIVATE_NETWORKS)
