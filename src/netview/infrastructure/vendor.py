"""Vendor lookup from the first three bytes of a MAC address."""

import contextlib
import csv
from pathlib import Path

from netview.domain.keys import is_private_mac, norm_mac

# Short built-in vendor list (first three MAC bytes), copied from the old LAN monitor.
_BUILTIN = {
    "Starlink (Tibro)": ["74249F"],
    "Dell": [
        "001422",
        "001E4F",
        "00219B",
        "002219",
        "0024E8",
        "0026B9",
        "141877",
        "1866DA",
        "18A99B",
        "24B6FD",
        "5CF9DD",
        "74867A",
        "782BCB",
        "842B2B",
        "90B11C",
        "B083FE",
        "B82A72",
        "B8AC6F",
        "BC305B",
        "C81F66",
        "D4AE52",
        "D4BED9",
        "ECF4BB",
        "F01FAF",
        "F8B156",
        "F8BC12",
        "F8DB88",
        "44A842",
        "989096",
        "A4BADB",
    ],
    "NETGEAR": [
        "00095B",
        "000FB5",
        "00146C",
        "00184D",
        "001B2F",
        "001E2A",
        "001F33",
        "00223F",
        "0024B2",
        "0026F2",
        "204E7F",
        "28C68E",
        "2CB05D",
        "30469A",
        "4494FC",
        "A021B7",
        "C03F0E",
        "E0469A",
        "E091F5",
        "9CD36D",
        "841B5E",
        "100D7F",
        "6CB0CE",
        "A040A0",
        "08BD43",
        "4C60DE",
    ],
    "Ubiquiti": [
        "245A4C",
        "7483C2",
        "788A20",
        "802AA8",
        "B4FBE4",
        "DC9FDB",
        "E063DA",
        "F09FC2",
        "FCECDA",
        "68D79A",
        "18E829",
        "0418D6",
        "44D9E7",
        "70A741",
        "AC8BA9",
        "602232",
        "E43883",
        "0CEA14",
        "28704E",
        "F492BF",
        "245A4C",
    ],
    "Roku": ["B0A737", "DC3A5E", "CC6DA0", "AC3A7A", "B83E59", "D83134", "345E08"],
    "Intel (PC Wi-Fi/Ethernet)": ["80B655", "C03C59", "C85EA9"],
    "Amazon": ["90395F"],
    "AltoBeam (Wi-Fi chip in budget IoT)": ["E82D79"],
    "TPV Display (TVs/monitors)": ["94BDBE"],
    "Gaoshengda (Wi-Fi module in TVs)": ["C4985C"],
    "Raspberry Pi": ["B827EB", "DCA632", "E45F01", "D83ADD", "2CCF67"],
    "Proxmox VM": ["BC2411"],
    "Hyper-V VM": ["00155D"],
    "VMware VM": ["005056", "000C29", "000569"],
    "VirtualBox VM": ["080027"],
}
BUILTIN_OUI = {p: v for v, prefixes in _BUILTIN.items() for p in prefixes}


def _load_oui_file(path: Path) -> dict[str, str]:
    """Read an IEEE oui.csv or a Wireshark manuf file into {PREFIX: vendor}."""
    table: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if text.startswith("Registry,"):
        for row in csv.reader(text.splitlines()[1:]):
            if len(row) >= 3 and row[0] == "MA-L":
                table[row[1].upper()] = row[2].strip()
    else:  # Wireshark manuf: 74:24:9F<TAB>Short<TAB>Long name
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            prefix = fields[0].replace(":", "").replace("-", "").upper()
            if len(prefix) == 6 and len(fields) >= 2:
                table[prefix] = (fields[2] if len(fields) >= 3 else fields[1]).strip()
    return table


class OuiVendorLookup:
    """Implements VendorLookup from the built-in table plus an optional OUI file."""

    def __init__(self, oui_file: Path | None = None) -> None:
        self._table = dict(BUILTIN_OUI)
        if oui_file is not None:
            # An unreadable file leaves the built-in table in place.
            with contextlib.suppress(OSError):
                self._table.update(_load_oui_file(oui_file))

    def vendor(self, mac: str | None) -> str:
        if not mac:
            return ""
        normal = norm_mac(mac)
        if normal is None:
            return ""
        known = self._table.get(normal.replace(":", "")[:6].upper(), "")
        if known:
            return known
        return "Random or local MAC" if is_private_mac(normal) else ""
