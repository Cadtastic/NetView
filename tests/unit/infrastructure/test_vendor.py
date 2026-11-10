from pathlib import Path

from netview.infrastructure.vendor import BUILTIN_OUI, OuiVendorLookup


def test_builtin_vendor() -> None:
    assert OuiVendorLookup().vendor("34:5e:08:b2:ae:f4") == "Roku"


def test_private_mac() -> None:
    assert OuiVendorLookup().vendor("02:09:f4:2b:ab:36") == "Random or local MAC"


def test_no_mac_is_empty() -> None:
    assert OuiVendorLookup().vendor(None) == ""


def test_unknown_vendor_is_empty() -> None:
    assert OuiVendorLookup().vendor("00:11:22:33:44:55") == ""


def test_builtin_table_size() -> None:
    assert BUILTIN_OUI["74249F"] == "Starlink (Tibro)"
    assert BUILTIN_OUI["00155D"] == "Hyper-V VM"


def test_ieee_csv_file(tmp_path: Path) -> None:
    f = tmp_path / "oui.csv"
    f.write_text(
        "\ufeffRegistry,Assignment,Organization Name,Organization Address\n"
        'MA-L,001122,"Acme, Inc.",Somewhere\n'
        "MA-S,A8BBCC1,Tiny Co,Elsewhere\n",
        encoding="utf-8",
    )
    lookup = OuiVendorLookup(f)
    assert lookup.vendor("00:11:22:33:44:55") == "Acme, Inc."
    assert lookup.vendor("a8:bb:cc:00:00:01") == ""
    assert lookup.vendor("34:5e:08:b2:ae:f4") == "Roku"


def test_wireshark_manuf_file(tmp_path: Path) -> None:
    f = tmp_path / "manuf"
    f.write_text("# comment\n00:11:22\tAcme\tAcme Corporation\n00-11-33\tShortOnly\n", encoding="utf-8")
    lookup = OuiVendorLookup(f)
    assert lookup.vendor("00:11:22:00:00:01") == "Acme Corporation"
    assert lookup.vendor("00:11:33:00:00:01") == "ShortOnly"


def test_missing_oui_file_falls_back_to_builtin(tmp_path: Path) -> None:
    lookup = OuiVendorLookup(tmp_path / "nope.csv")
    assert lookup.vendor("34:5e:08:b2:ae:f4") == "Roku"


def test_garbage_mac_is_empty() -> None:
    assert OuiVendorLookup().vendor("nonsense") == ""
