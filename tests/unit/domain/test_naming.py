from itertools import permutations

from netview.domain.naming import (
    NAME_RANKS,
    TYPE_RANKS,
    NameClaim,
    TypeClaim,
    best_claim,
    best_type,
    display_name,
)


def claim(source: str, name: str = "n", checked: int = 0) -> NameClaim:
    return NameClaim("k", name or "", source, NAME_RANKS[source], checked)


def test_upnp_beats_dhcp_in_any_order():
    claims = [claim("DHCP", "dhcp"), claim("UPnP", "upnp"), claim("DNS", "dns")]
    for order in permutations(claims):
        assert best_claim(order).source == "UPnP"


def test_equal_rank_prefers_newer():
    old = claim("mDNS", "old", 1)
    new = claim("mDNS", "new", 2)
    assert best_claim([new, old]).name == "new"
    assert best_claim([old, new]).name == "new"


def test_empty_names_ignored():
    assert best_claim([claim("hostname", "", 5), claim("DNS", "dns", 1)]).name == "dns"
    assert best_claim([claim("hostname", "")]) is None
    assert best_claim([]) is None


def test_display_name_nickname_wins():
    assert display_name("Roku TV (Bedroom)", claim("UPnP", "x"), "x") == "Roku TV (Bedroom)"


def test_display_name_claim_before_watch_label():
    assert display_name(None, claim("UPnP", "upnp"), "label") == "upnp"


def test_display_name_watch_label():
    assert display_name(None, None, "R720 iDRAC") == "R720 iDRAC"


def test_display_name_empty():
    assert display_name(None, None, None) == ""


def _type(source: str, kind: str = "t", checked: int = 0) -> TypeClaim:
    return TypeClaim("k", kind, "r", source, checked)


def test_inspection_type_beats_vendor_type_in_any_order() -> None:
    claims = [_type("vendor", "Roku device", 99), _type("inspection", "printer", 1)]
    for order in permutations(claims):
        best = best_type(order)
        assert best is not None and best.type == "printer"


def test_newer_vendor_type_wins_between_two_vendor_claims() -> None:
    old, new = _type("vendor", "old", 1), _type("vendor", "new", 2)
    assert best_type([new, old]).type == "new"  # type: ignore[union-attr]
    assert best_type([old, new]).type == "new"  # type: ignore[union-attr]


def test_unknown_source_ranks_between_vendor_and_inspection() -> None:
    assert TYPE_RANKS == {"inspection": 2.0, "vendor": 1.0}
    assert best_type([_type("vendor", "v"), _type("other", "o")]).type == "o"  # type: ignore[union-attr]
    assert best_type([_type("inspection", "i"), _type("other", "o")]).type == "i"  # type: ignore[union-attr]


def test_best_type_ignores_empty_types_and_handles_none() -> None:
    assert best_type([]) is None
    assert best_type([_type("inspection", "")]) is None
    assert best_type([_type("inspection", ""), _type("vendor", "v")]).type == "v"  # type: ignore[union-attr]
