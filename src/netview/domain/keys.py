"""Device keys and MAC helpers."""

import re

SELF_KEY = "self"

_HEX = re.compile(r"^[0-9a-f]{1,2}$")


def norm_mac(raw: str) -> str | None:
    """Normalise a MAC to lower-case colon form; None for invalid, broadcast, zero or multicast."""
    parts = re.split(r"[:-]", raw.strip())
    if len(parts) != 6 or not all(_HEX.match(p.lower()) for p in parts):
        return None
    mac = ":".join(p.zfill(2) for p in parts).lower()
    if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") or mac.startswith("01:00:5e"):
        return None
    return mac


def key_for(ip: str, mac: str | None, is_self: bool) -> str:
    """Device key: 'self', else the MAC, else 'ip:<ip>'."""
    if is_self:
        return SELF_KEY
    return mac if mac else f"ip:{ip}"


def is_private_mac(mac: str) -> bool:
    """True when the locally-administered bit is set (randomised/private address)."""
    return bool(int(mac.split(":")[0], 16) & 0x02)
