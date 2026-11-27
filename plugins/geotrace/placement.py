"""Turns the SDK's raw traceroute hops into placed hops (spec 8.2-8.3)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from netview.sdk import TraceHop

from .addresses import AddressClass, classify
from .geo import HopLocator, Location
from .model import Hop

_EARTH_RADIUS_KM = 6371.0088
_KM_PER_MS = 100.0
_SLACK_KM = 200.0


@dataclass(frozen=True)
class Home:
    lat: float
    lon: float
    label: str


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dphi = phi2 - phi1
    dlam = math.radians(b_lon - a_lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _hop(
    raw: TraceHop,
    ip: str | None,
    placement: str = "none",
    where: Location | None = None,
    *,
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    network: bool = False,
    plausible: bool = True,
) -> Hop:
    """Build a Hop. `where` supplies place text and coordinates; `network` also copies its ASN."""
    return Hop(
        n=raw.n,
        ip=ip,
        rtts_ms=tuple(raw.rtts_ms),
        city=city if city is not None else (where.city if where else ""),
        region=where.region if where else "",
        country=where.country if where else "",
        lat=lat if lat is not None else (where.lat if where else None),
        lon=lon if lon is not None else (where.lon if where else None),
        asn=where.asn if where and network else None,
        as_org=where.as_org if where and network else "",
        placement=placement,
        plausible=plausible,
    )


def _plausible(raw: TraceHop, location: Location, home: Home | None) -> bool:
    if home is None:
        return True
    rtts = [r for r in raw.rtts_ms if r is not None]
    if not rtts:
        return True
    distance = haversine_km(home.lat, home.lon, location.lat, location.lon)
    return distance <= min(rtts) * _KM_PER_MS + _SLACK_KM


def place_hops(
    hops: Sequence[TraceHop],
    home: Home | None,
    locator: HopLocator | None,
) -> tuple[Hop, ...]:
    ips: list[str | None] = []
    kinds: list[AddressClass] = []
    located: dict[int, Location] = {}
    for index, raw in enumerate(hops):
        ip = raw.ip.split("%", 1)[0] if raw.ip is not None else None
        kind = classify(ip) if ip is not None else "none"
        # An unparseable address is kept as given and treated like a silent hop.
        ips.append(raw.ip if kind == "none" else ip)
        kinds.append(kind)
        if kind == "public" and ip is not None and locator is not None:
            found = locator.locate(ip)
            if found is not None:
                located[index] = found

    def next_located(after: int) -> Location | None:
        later = [i for i in located if i > after]
        return located[min(later)] if later else None

    first_located = located[min(located)] if located else None

    placed: list[Hop] = []
    left_home = False  # a carrier (CGNAT) or public hop came earlier: a private address now is the ISP's, not ours
    for index, raw in enumerate(hops):
        ip, kind = ips[index], kinds[index]
        away = left_home
        left_home = left_home or kind in ("cgnat", "public")
        if kind == "private" and away:
            target = next_located(index)
            placed.append(_hop(raw, ip, "assumed", target) if target is not None else _hop(raw, ip))
        elif kind == "private" and home is not None:
            placed.append(_hop(raw, ip, "home", city=home.label, lat=home.lat, lon=home.lon))
        elif kind == "private" and first_located is not None:
            placed.append(_hop(raw, ip, "home", first_located))
        elif kind == "cgnat" and (target := next_located(index)) is not None:
            placed.append(_hop(raw, ip, "assumed", target))
        elif index in located:
            found = located[index]
            placed.append(
                _hop(raw, ip, "located", found, network=True, plausible=_plausible(raw, found, home))
            )
        else:
            placed.append(_hop(raw, ip))
    return tuple(placed)
