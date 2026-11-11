from netview.domain.device_kind import os_hint, vendor_type


def test_vendor_type_by_vendor_name() -> None:
    assert vendor_type("Roku, Inc", None, False) == "Roku device"
    assert vendor_type("Raspberry Pi Trading Ltd", None, False) == "Raspberry Pi"
    assert vendor_type("Space Exploration Technologies (Starlink)", None, False) == "Starlink router"


def test_intel_depends_on_ttl() -> None:
    assert vendor_type("Intel Corporate", 128, False) == "Windows PC"
    assert vendor_type("Intel Corporate", 64, False) == "PC or laptop"
    assert vendor_type("Intel Corporate", None, False) == "PC or laptop"


def test_private_mac_fallback_and_windows_ttl() -> None:
    assert vendor_type("", None, True) == "Phone, tablet or laptop"
    assert vendor_type("", 128, False) == "Windows PC"
    assert vendor_type("", 64, False) == ""
    assert vendor_type("", None, False) == ""


def test_os_hint() -> None:
    assert os_hint(None) == ""
    assert os_hint(0) == ""
    assert os_hint(64) == "Linux/Apple/Android/embedded"
    assert os_hint(128) == "Windows"
    assert os_hint(255) == "Network device"
