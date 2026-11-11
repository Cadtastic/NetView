"""Address helpers that need no I/O."""

import ipaddress


def has_lan_address(ip: str) -> bool:
    """False for loopback, link-local, unspecified or unparsable addresses."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (address.is_loopback or address.is_link_local or address.is_unspecified)
