"""Hop locator over the DB-IP Lite city and ASN databases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import maxminddb


@dataclass(frozen=True)
class Location:
    city: str
    region: str
    country: str
    lat: float
    lon: float
    asn: int | None
    as_org: str


class HopLocator(Protocol):
    def locate(self, ip: str) -> Location | None: ...


def _name(record: Any) -> str:
    if isinstance(record, dict):
        names = record.get("names")
        if isinstance(names, dict):
            value = names.get("en")
            if isinstance(value, str):
                return value
    return ""


class DbipLocator:
    """Looks an address up in the city file and, when there is one, the ASN file.

    close() releases both files (a mapped file stays locked on Windows) and is safe to repeat.
    """

    def __init__(
        self,
        city_path: Path | None,
        asn_path: Path | None,
        open_reader: Callable[[Path], Any] = maxminddb.open_database,
    ) -> None:
        self._city: Any = open_reader(city_path) if city_path is not None else None
        self._asn: Any = None
        try:
            self._asn = open_reader(asn_path) if asn_path is not None else None
        except Exception:
            self.close()
            raise

    def locate(self, ip: str) -> Location | None:
        city = self._city
        if city is None:
            return None
        try:
            record = city.get(ip)
        except (ValueError, OSError, RuntimeError):
            return None
        if not isinstance(record, dict):
            return None
        place = record.get("location")
        if not isinstance(place, dict):
            return None
        lat, lon = place.get("latitude"), place.get("longitude")
        if not isinstance(lat, int | float) or not isinstance(lon, int | float):
            return None
        subdivisions = record.get("subdivisions")
        region = _name(subdivisions[0]) if isinstance(subdivisions, list) and subdivisions else ""
        country = record.get("country")
        iso = country.get("iso_code") if isinstance(country, dict) else None
        asn, as_org = self._asn_of(ip)
        return Location(
            city=_name(record.get("city")),
            region=region,
            country=iso if isinstance(iso, str) else "",
            lat=float(lat),
            lon=float(lon),
            asn=asn,
            as_org=as_org,
        )

    def _asn_of(self, ip: str) -> tuple[int | None, str]:
        if self._asn is None:
            return None, ""
        try:
            record = self._asn.get(ip)
        except (ValueError, OSError, RuntimeError):
            return None, ""
        if not isinstance(record, dict):
            return None, ""
        number = record.get("autonomous_system_number")
        org = record.get("autonomous_system_organization")
        return (
            number if isinstance(number, int) else None,
            org if isinstance(org, str) else "",
        )

    def close(self) -> None:
        city, asn = self._city, self._asn
        self._city = None
        self._asn = None
        for reader in (city, asn):
            if reader is not None:
                reader.close()
