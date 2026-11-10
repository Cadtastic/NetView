from itertools import permutations

from netview.domain.naming import NAME_RANKS, NameClaim, best_claim, display_name


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
