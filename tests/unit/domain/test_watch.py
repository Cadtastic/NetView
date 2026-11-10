import pytest

from netview.domain.errors import ValidationError
from netview.domain.watch import Watch, parse_watch_spec


def test_parse_full():
    w = parse_watch_spec("192.168.1.128:443,22=R720 iDRAC")
    assert w == Watch("192.168.1.128", (443, 22), "R720 iDRAC")


def test_spec_round_trips():
    for s in ("192.168.1.128:443,22=R720 iDRAC", "10.0.0.1", "10.0.0.1:80", "10.0.0.1=x"):
        assert parse_watch_spec(s).spec() == s


def test_port_out_of_range():
    with pytest.raises(ValidationError):
        parse_watch_spec("10.0.0.1:70000")
    with pytest.raises(ValidationError):
        parse_watch_spec("10.0.0.1:0")


def test_bad_ip():
    with pytest.raises(ValidationError):
        parse_watch_spec("10.0.0.300")
