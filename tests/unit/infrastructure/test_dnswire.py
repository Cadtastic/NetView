"""DNS wire format: building queries and parsing hostile or truncated answers (Review focus 3)."""

import contextlib
import random
import struct

import pytest

from netview.application.ports.probes import DnsRecord
from netview.infrastructure.net import dnswire


def _name(text: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in text.split(".") if p) + b"\0"


def _rr(name: bytes, rtype: int, rdata: bytes) -> bytes:
    return name + struct.pack(">HHIH", rtype, 1, 120, len(rdata)) + rdata


def _answer() -> bytes:
    """An mDNS-style answer with a PTR, a TXT, an SRV and an A record (the last one compressed)."""
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 4, 0, 0)
    service = _name("_http._tcp.local")
    instance = _name("Printer._http._tcp.local")
    host = _name("printer.local")
    txt = b"".join(bytes([len(s)]) + s for s in (b"model=X1", b"rp=queue"))
    srv = struct.pack(">HHH", 0, 0, 8080) + host
    first = _rr(service, 12, instance)
    second = _rr(instance, 16, txt)
    third = _rr(instance, 33, srv)
    # the fourth owner name points back at the first record's name (offset 12)
    fourth = _rr(b"\xc0\x0c", 1, bytes([192, 0, 2, 7]))
    return header + first + second + third + fourth


def test_build_query_sets_the_unicast_bit_and_labels() -> None:
    packet = dnswire.build_query(0x1234, "_services._dns-sd._udp.local", 12, True)
    tid, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", packet[:12])
    assert (tid, flags, qd, an, ns, ar) == (0x1234, 0, 1, 0, 0, 0)
    assert packet[12:-4] == _name("_services._dns-sd._udp.local")
    assert struct.unpack(">HH", packet[-4:]) == (12, 0x8001)
    plain = dnswire.build_query(1, "a.local", 1, False)
    assert struct.unpack(">HH", plain[-4:]) == (1, 1)


@pytest.mark.parametrize("bad", ["a" * 64 + ".local", "café.local"])
def test_build_query_rejects_labels_it_cannot_encode(bad: str) -> None:
    with pytest.raises(ValueError):
        dnswire.build_query(1, bad, 12, False)


def test_parse_records_returns_ptr_txt_srv_and_a() -> None:
    records = dnswire.parse_records(_answer())
    assert records == [
        DnsRecord("_http._tcp.local", 12, "Printer._http._tcp.local"),
        DnsRecord("Printer._http._tcp.local", 16, ("model=X1", "rp=queue")),
        DnsRecord("Printer._http._tcp.local", 33, "printer.local:8080"),
        DnsRecord("_http._tcp.local", 1, "192.0.2.7"),
    ]


def test_a_two_label_pointer_loop_raises_value_error() -> None:
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    # offset 12 points at 14 and offset 14 points back at 12
    loop = b"\xc0\x0e\xc0\x0c" + struct.pack(">HHIH", 1, 1, 0, 4) + bytes(4)
    with pytest.raises(ValueError):
        dnswire.parse_records(header + loop)


def test_a_self_pointing_name_raises_value_error() -> None:
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    with pytest.raises(ValueError):
        dnswire.parse_records(header + b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 0, 4) + bytes(4))


def test_every_truncation_of_a_good_packet_raises_value_error_only() -> None:
    packet = _answer()
    for cut in range(len(packet)):
        with pytest.raises(ValueError):
            dnswire.parse_records(packet[:cut])


def test_a_record_length_that_runs_past_the_packet_raises_value_error() -> None:
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    record = _name("a.local") + struct.pack(">HHIH", 16, 1, 0, 200) + b"\x03abc"
    with pytest.raises(ValueError):
        dnswire.parse_records(header + record)


def test_a_txt_string_longer_than_its_record_is_clipped() -> None:
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    record = _name("a.local") + struct.pack(">HHIH", 16, 1, 0, 4) + b"\x09abc"
    assert dnswire.parse_records(header + record) == [DnsRecord("a.local", 16, ("abc",))]


def test_random_garbage_never_raises_anything_but_value_error() -> None:
    rng = random.Random(7)
    for _ in range(300):
        blob = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 80)))
        with contextlib.suppress(ValueError):
            dnswire.parse_records(blob)
