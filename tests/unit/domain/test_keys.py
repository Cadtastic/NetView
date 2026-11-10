from netview.domain.keys import SELF_KEY, is_private_mac, key_for, norm_mac


def test_norm_mac_dashes_upper():
    assert norm_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"


def test_norm_mac_pads_short_octets():
    assert norm_mac("a:b:c:d:e:f") == "0a:0b:0c:0d:0e:0f"


def test_norm_mac_broadcast_is_none():
    assert norm_mac("ff:ff:ff:ff:ff:ff") is None


def test_norm_mac_zero_is_none():
    assert norm_mac("00:00:00:00:00:00") is None


def test_norm_mac_multicast_is_none():
    assert norm_mac("01:00:5e:00:00:fb") is None


def test_norm_mac_garbage_is_none():
    assert norm_mac("not a mac") is None
    assert norm_mac("aa:bb:cc") is None


def test_key_for_ip_fallback():
    assert key_for("192.168.1.5", None, False) == "ip:192.168.1.5"


def test_key_for_mac():
    assert key_for("192.168.1.5", "aa:bb:cc:dd:ee:ff", False) == "aa:bb:cc:dd:ee:ff"


def test_key_for_self():
    assert key_for("192.168.1.95", None, True) == "self" == SELF_KEY


def test_is_private_mac():
    assert is_private_mac("02:09:f4:2b:ab:36") is True
    assert is_private_mac("34:5e:08:b2:ae:f4") is False
