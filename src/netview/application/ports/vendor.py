"""Vendor lookup port."""

from typing import Protocol


class VendorLookup(Protocol):
    def vendor(self, mac: str | None) -> str:
        """Empty string when unknown, "Random or local MAC" for private MACs."""
        ...
