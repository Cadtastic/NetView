from pathlib import Path

import pytest

from netview.sdk import SnmpTarget, SnmpTimeout, SnmpV2c
from netview.sdk.testing.fakes import FakeSnmpClient
from netview.sdk.testing.snmpwalk import parse_snmpwalk


def one(line: str) -> object:
    rows = parse_snmpwalk(line)
    assert len(rows) == 1
    assert rows[0][0] == (1, 3, 6, 1, 2, 1, 1, 1, 0)
    return rows[0][1]


def test_string_is_utf8_bytes() -> None:
    assert one('.1.3.6.1.2.1.1.1.0 = STRING: "GSM7248 \u00e9"') == "GSM7248 \u00e9".encode()


def test_empty_quoted_string() -> None:
    assert one('.1.3.6.1.2.1.1.1.0 = STRING: ""') == b""


def test_bare_empty_value() -> None:
    assert one('.1.3.6.1.2.1.1.1.0 = ""') == b""


def test_hex_string() -> None:
    assert one(".1.3.6.1.2.1.1.1.0 = Hex-STRING: 00 1A 2B 3C 4D 5E") == bytes.fromhex("001A2B3C4D5E")


def test_integer_plain_and_named() -> None:
    assert one(".1.3.6.1.2.1.1.1.0 = INTEGER: 7") == 7
    assert one(".1.3.6.1.2.1.1.1.0 = INTEGER: up(1)") == 1
    assert one(".1.3.6.1.2.1.1.1.0 = INTEGER: -2") == -2


def test_counters_and_gauge() -> None:
    assert one(".1.3.6.1.2.1.1.1.0 = Counter32: 4294967295") == 4294967295
    assert one(".1.3.6.1.2.1.1.1.0 = Counter64: 18446744073709551615") == 18446744073709551615
    assert one(".1.3.6.1.2.1.1.1.0 = Gauge32: 1000000000") == 1000000000


def test_timeticks() -> None:
    assert one(".1.3.6.1.2.1.1.1.0 = Timeticks: (123456) 0:20:34.56") == 123456


def test_oid_value() -> None:
    assert one(".1.3.6.1.2.1.1.1.0 = OID: .1.3.6.1.4.1.4526.100") == (1, 3, 6, 1, 4, 1, 4526, 100)


def test_ipaddress() -> None:
    assert one(".1.3.6.1.2.1.1.1.0 = IpAddress: 192.168.1.4") == "192.168.1.4"


def test_multiline_string_continuation() -> None:
    rows = parse_snmpwalk('.1.3.6.1.2.1.1.1.0 = STRING: "a\nb"\n.1.3.6.1.2.1.1.2.0 = INTEGER: 1\n')
    assert rows[0][1] == b"a\nb"
    assert rows[1][0] == (1, 3, 6, 1, 2, 1, 1, 2, 0)


def test_fake_walk_prefix_order() -> None:
    client = FakeSnmpClient(
        [((1, 3, 2), 2), ((1, 3, 1), 1), ((1, 4, 1), 9), ((1, 3, 10), 10)],
    )
    t = SnmpTarget("h", SnmpV2c("c"))
    assert client.walk(t, (1, 3)) == [((1, 3, 1), 1), ((1, 3, 2), 2), ((1, 3, 10), 10)]
    assert client.walk(t, (1, 3), max_rows=2) == [((1, 3, 1), 1), ((1, 3, 2), 2)]
    assert ("walk", (1, 3)) in client.calls


def test_fake_get_missing_is_none() -> None:
    client = FakeSnmpClient([((1, 3, 1), 1)])
    t = SnmpTarget("h", SnmpV2c("c"))
    assert client.get(t, [(1, 3, 1), (1, 3, 2)]) == {(1, 3, 1): 1, (1, 3, 2): None}


def test_fake_fail_with_raises() -> None:
    client = FakeSnmpClient([])
    client.fail_with = SnmpTimeout("down")
    with pytest.raises(SnmpTimeout):
        client.get(SnmpTarget("h", SnmpV2c("c")), [(1,)])


def test_from_walk_file(tmp_path: Path) -> None:
    p = tmp_path / "w.txt"
    p.write_text(".1.3.6.1.2.1.1.3.0 = Timeticks: (5) 0:00:00.05\n", encoding="utf-8")
    client = FakeSnmpClient.from_walk_file(p)
    oid = (1, 3, 6, 1, 2, 1, 1, 3, 0)
    assert client.get(SnmpTarget("h", SnmpV2c("c")), [oid])[oid] == 5


def test_comment_lines_skipped() -> None:
    text = '# synthetic walk\n.1.3.6.1.2.1.1.1.0 = STRING: "x"\n  # another\n'
    assert parse_snmpwalk(text) == [((1, 3, 6, 1, 2, 1, 1, 1, 0), b"x")]


def test_hex_string_wrapped_over_lines() -> None:
    data = bytes(range(20))
    first = " ".join(f"{b:02X}" for b in data[:16])
    second = " ".join(f"{b:02X}" for b in data[16:])
    text = f".1.3.6.1.2.1.1.1.0 = Hex-STRING: {first} \n{second} \n.1.3.6.1.2.1.1.2.0 = INTEGER: 5\n"
    rows = parse_snmpwalk(text)
    assert rows == [((1, 3, 6, 1, 2, 1, 1, 1, 0), data), ((1, 3, 6, 1, 2, 1, 1, 2, 0), 5)]
