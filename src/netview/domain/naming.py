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


TYPE_RANKS: Mapping[str, float] = {"inspection": 2.0, "vendor": 1.0}
_UNKNOWN_TYPE_RANK = 1.5


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
    checked_ms: int = 0


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


def best_type(claims: Iterable[TypeClaim]) -> TypeClaim | None:
    """Highest source rank wins; ties go to the newest check, then to the later claim.

    A source that is not in ``TYPE_RANKS`` ranks between vendor and inspection. Empty types are ignored.
    """
    best: TypeClaim | None = None
    best_key: tuple[float, int] = (0.0, 0)
    for c in claims:
        if not c.type:
            continue
        key = (TYPE_RANKS.get(c.source, _UNKNOWN_TYPE_RANK), c.checked_ms)
        if best is None or key >= best_key:
            best, best_key = c, key
    return best


def display_name(nickname: str | None, best: NameClaim | None, watch_label: str | None) -> str:
    """Nickname, else best claimed name, else watch label, else empty."""
    if nickname:
        return nickname
    if best is not None and best.name:
        return best.name
    return watch_label or ""
