import pytest

from netview.sdk import SnmpV2c, SnmpV3, parse_oid


def test_parse_oid_leading_dot() -> None:
    assert parse_oid(".1.3.6.1") == (1, 3, 6, 1)


def test_parse_oid_plain() -> None:
    assert parse_oid("1.3.6") == (1, 3, 6)


def test_parse_oid_rejects_text() -> None:
    with pytest.raises(ValueError):
        parse_oid("a.b")


def test_credentials_repr_hides_secret() -> None:
    assert "comS3cret" not in repr(SnmpV2c("comS3cret"))
    text = repr(SnmpV3("u", "sha", "authS3cret", "des", "privS3cret"))
    assert "authS3cret" not in text
    assert "privS3cret" not in text
    assert repr(SnmpV2c("x")) == "SnmpV2c(community=***)"
