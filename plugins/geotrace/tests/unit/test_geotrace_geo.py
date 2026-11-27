from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from netview_local_plugins.geotrace.geo import DbipLocator, Location


class FakeReader:
    def __init__(self, records: dict[str, Any]) -> None:
        self.records = records
        self.closed = 0

    def get(self, ip: str) -> Any:
        return self.records.get(ip)

    def metadata(self) -> Any:
        return SimpleNamespace(node_count=5000)

    def close(self) -> None:
        self.closed += 1


CITY = {
    "8.8.8.8": {
        "city": {"names": {"en": "Mountain View"}},
        "subdivisions": [{"names": {"en": "California"}}],
        "country": {"iso_code": "US"},
        "location": {"latitude": 37.4, "longitude": -122.08},
    },
    "9.9.9.9": {"country": {"iso_code": "CH"}},
}
ASN = {"8.8.8.8": {"autonomous_system_number": 15169, "autonomous_system_organization": "Google LLC"}}


def make(city: bool = True, asn: bool = True) -> tuple[DbipLocator, dict[str, FakeReader]]:
    readers: dict[str, FakeReader] = {}

    def opener(path: Any) -> FakeReader:
        reader = FakeReader(CITY if "city" in str(path) else ASN)
        readers[Path(str(path)).name] = reader
        return reader

    locator = DbipLocator(
        Path("city.mmdb") if city else None,
        Path("asn.mmdb") if asn else None,
        open_reader=opener,
    )
    return locator, readers


def test_locates_city_and_asn() -> None:
    locator, _ = make()
    assert locator.locate("8.8.8.8") == Location(
        city="Mountain View",
        region="California",
        country="US",
        lat=37.4,
        lon=-122.08,
        asn=15169,
        as_org="Google LLC",
    )


def test_record_without_coordinates_is_none() -> None:
    locator, _ = make()
    assert locator.locate("9.9.9.9") is None
    assert locator.locate("1.1.1.1") is None


def test_missing_asn_database_gives_none_asn() -> None:
    locator, _ = make(asn=False)
    loc = locator.locate("8.8.8.8")
    assert loc is not None
    assert loc.asn is None
    assert loc.as_org == ""


def test_missing_city_database_gives_none() -> None:
    locator, _ = make(city=False)
    assert locator.locate("8.8.8.8") is None


def test_garbage_ip_is_none() -> None:
    class Raising(FakeReader):
        def get(self, ip: str) -> Any:
            raise ValueError("bad address")

    locator = DbipLocator(Path("city.mmdb"), None, open_reader=lambda p: Raising({}))
    assert locator.locate("nope") is None


def test_close_closes_both_and_is_idempotent() -> None:
    locator, readers = make()
    locator.close()
    locator.close()
    assert readers["city.mmdb"].closed == 1
    assert readers["asn.mmdb"].closed == 1
    assert locator.locate("8.8.8.8") is None
