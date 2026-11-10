"""Name claims, type claims, hints and display-name resolution."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

NAME_RANKS: Mapping[str, float] = {
    "hostname": 9,
    "UPnP": 6,
    "AirPlay": 5,
    "NetBIOS": 4,
    "DHCP": 3.5,
    "mDNS": 3,
    "RDP certificate": 2,
    "DNS": 1,
}


@dataclass(frozen=True)
class NameClaim:
    key: str
    name: str
    source: str
    rank: float
    checked_ms: int


@dataclass(frozen=True)
class TypeClaim:
    key: str
    type: str
    reason: str
    source: str


@dataclass(frozen=True)
class Hint:
    key: str
    text: str
    source: str


def best_claim(claims: Iterable[NameClaim]) -> NameClaim | None:
    """Highest rank wins; ties go to the newest check. Empty names are ignored."""
    best: NameClaim | None = None
    for c in claims:
        if not c.name:
            continue
        if best is None or (c.rank, c.checked_ms) > (best.rank, best.checked_ms):
            best = c
    return best


def display_name(nickname: str | None, best: NameClaim | None, watch_label: str | None) -> str:
    """Nickname, else best claimed name, else watch label, else empty."""
    if nickname:
        return nickname
    if best is not None and best.name:
        return best.name
    return watch_label or ""
