from __future__ import annotations

from netview_local_plugins.geotrace.geo import Location
from netview_local_plugins.geotrace.placement import Home, haversine_km, place_hops

from netview.sdk import TraceHop

HOME = Home(lat=39.74, lon=-104.99, label="Home")


class FakeLocator:
    def __init__(self, table: dict[str, Location]) -> None:
        self.table = table

    def locate(self, ip: str) -> Location | None:
        return self.table.get(ip)


def loc(city: str, lat: float, lon: float, asn: int = 7922) -> Location:
    return Location(city, "XX", "US", lat, lon, asn, f"AS{asn}")


def hop(n: int, ip: str | None, *rtts: float | None) -> TraceHop:
    return TraceHop(n=n, ip=ip, rtts_ms=tuple(rtts))


DENVER = loc("Denver", 39.74, -104.99)
DALLAS = loc("Dallas", 32.78, -96.80)
PHOENIX = loc("Phoenix", 33.45, -112.07)
LA = loc("Los Angeles", 34.05, -118.24)
SJ = loc("San Jose", 37.34, -121.89)
TABLE = {
    "8.8.1.1": DENVER,
    "8.8.2.2": DALLAS,
    "8.8.3.3": PHOENIX,
    "8.8.4.4": LA,
    "8.8.6.6": SJ,
}


def mockup_route() -> list[TraceHop]:
    return [
        hop(1, "10.27.10.1", 0.4),
        hop(2, "192.168.1.1", 1.0),
        hop(3, "100.64.0.1", 30.0),
        hop(4, "8.8.1.1", 31.0, 32.0),
        hop(5, "8.8.2.2", 45.0),
        hop(6, "8.8.3.3", 50.0),
        hop(7, "8.8.4.4", 55.0),
        hop(8, None),
        hop(9, "8.8.6.6", 60.0),
    ]


def test_mockup_route() -> None:
    hops = place_hops(mockup_route(), HOME, FakeLocator(TABLE))
    kinds = [h.placement for h in hops]
    assert kinds == ["home", "home", "assumed", "located", "located", "located", "located", "none", "located"]
    assert (hops[0].lat, hops[0].lon) == (HOME.lat, HOME.lon)
    assert hops[0].city == "Home"
    assert (hops[2].lat, hops[2].lon) == (DENVER.lat, DENVER.lon)
    assert hops[2].city == "Denver"
    assert hops[2].ip == "100.64.0.1"
    assert hops[3].city == "Denver" and hops[3].asn == 7922
    assert hops[7].lat is None and hops[7].ip is None
    assert hops[3].rtts_ms == (31.0, 32.0)
    assert all(h.plausible for h in hops)


def test_two_ms_hop_in_london_is_implausible() -> None:
    london = loc("London", 51.5, -0.12, 2856)
    hops = place_hops([hop(1, "8.8.9.9", 2.0, 3.0)], HOME, FakeLocator({"8.8.9.9": london}))
    assert hops[0].placement == "located"
    assert hops[0].plausible is False


def test_no_home_private_hops_sit_at_first_located_hop() -> None:
    hops = place_hops(mockup_route(), None, FakeLocator(TABLE))
    assert hops[0].placement == "home"
    assert (hops[0].lat, hops[0].lon) == (DENVER.lat, DENVER.lon)
    assert (hops[1].lat, hops[1].lon) == (DENVER.lat, DENVER.lon)
    assert all(h.plausible for h in hops)


def test_everything_silent_after_gateway() -> None:
    route = [hop(1, "10.27.10.1", 0.4), hop(2, None), hop(3, None), hop(4, "192.168.1.1", 1.0)]
    hops = place_hops(route, None, FakeLocator(TABLE))
    assert not any(h.placement == "located" for h in hops)
    assert [h.placement for h in hops] == ["none"] * 4
    homed = place_hops(route, HOME, FakeLocator(TABLE))
    assert [h.placement for h in homed] == ["home", "none", "none", "home"]


def test_cgnat_with_no_later_located_hop_is_none() -> None:
    hops = place_hops([hop(1, "100.64.0.1", 20.0), hop(2, None)], HOME, FakeLocator(TABLE))
    assert [h.placement for h in hops] == ["none", "none"]


def test_starlink_private_hop_after_the_carrier_hop_is_not_home() -> None:
    route = [hop(1, "192.168.1.1", 0.4), hop(2, "100.64.0.1", 30.0), hop(3, "172.16.250.30", 32.0), hop(4, "8.8.2.2", 40.0)]
    hops = place_hops(route, HOME, FakeLocator(TABLE))
    assert [h.placement for h in hops] == ["home", "assumed", "assumed", "located"]
    assert (hops[2].lat, hops[2].lon) == (DALLAS.lat, DALLAS.lon)


def test_private_hop_after_a_public_hop_is_not_home_and_none_without_a_later_located_hop() -> None:
    route = [hop(1, "192.168.1.1", 0.4), hop(2, "8.8.1.1", 5.0), hop(3, "10.9.9.9", 6.0)]
    assert [h.placement for h in place_hops(route, HOME, FakeLocator(TABLE))] == ["home", "located", "none"]


def test_unlocatable_public_hop_is_none_and_no_locator_ok() -> None:
    hops = place_hops([hop(1, "9.9.9.9", 5.0)], HOME, None)
    assert hops[0].placement == "none" and hops[0].lat is None


def test_scope_suffix_stripped_and_unparseable_is_silent() -> None:
    hops = place_hops([hop(1, "fe80::1%eth0", 0.5), hop(2, "not-an-ip", 1.0)], HOME, FakeLocator({}))
    assert hops[0].ip == "fe80::1" and hops[0].placement == "home"
    assert hops[1].ip == "not-an-ip" and hops[1].placement == "none"


def test_located_without_rtt_or_home_stays_plausible() -> None:
    london = loc("London", 51.5, -0.12)
    table = FakeLocator({"8.8.9.9": london})
    assert place_hops([hop(1, "8.8.9.9", None)], HOME, table)[0].plausible
    assert place_hops([hop(1, "8.8.9.9", 2.0)], None, table)[0].plausible


def test_haversine() -> None:
    assert haversine_km(0, 0, 0, 0) == 0
    assert 5500 < haversine_km(HOME.lat, HOME.lon, 51.5, -0.12) < 8000
