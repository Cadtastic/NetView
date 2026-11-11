"""The strict protobuf reader the Starlink plugin uses (ported from LM 1061-1090)."""

import contextlib
import struct
from pathlib import Path

import pytest

from netview.plugins.builtin.starlink.protobuf import fields, varint

FIXTURE = Path(__file__).parents[2] / "fixtures" / "starlink" / "clients.bin"


def test_varint_reads_one_and_many_bytes() -> None:
    assert varint(b"\x05", 0) == (5, 1)
    assert varint(b"\xac\x02", 0) == (300, 2)
    assert varint(b"xx\x96\x01", 2) == (150, 4)


def test_varint_truncated_or_endless_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        varint(b"\x80", 0)
    with pytest.raises(ValueError):
        varint(b"", 0)
    with pytest.raises(ValueError):
        varint(b"\xff" * 11 + b"\x01", 0)


def test_fields_reads_every_wire_type() -> None:
    buf = (
        b"\x08\x96\x01"  # field 1, varint 150
        + b"\x12\x03abc"  # field 2, 3 bytes
        + b"\x1d"
        + struct.pack("<f", 1.5)  # field 3, fixed32
        + b"\x21"
        + struct.pack("<d", 2.5)  # field 4, fixed64
        + b"\x08\x07"  # field 1 again
    )
    got = fields(buf)
    assert got[1] == [150, 7]
    assert got[2] == [b"abc"]
    assert struct.unpack("<f", got[3][0])[0] == 1.5  # type: ignore[arg-type]
    assert struct.unpack("<d", got[4][0])[0] == 2.5  # type: ignore[arg-type]
    assert fields(b"") == {}


@pytest.mark.parametrize(
    "buf",
    [
        b"\x12\x05abc",  # length runs past the end
        b"\x12",  # length missing
        b"\x1d\x00\x00",  # fixed32 cut short
        b"\x21\x00\x00\x00",  # fixed64 cut short
        b"\x08",  # varint value missing
        b"\x0b",  # wire type 3 (start group)
        b"\x0c",  # wire type 4 (end group)
        b"\x0e\x00",  # wire type 6
        b"\x00\x01",  # field number 0
    ],
)
def test_truncated_or_unknown_input_raises_value_error_never_index_error(buf: bytes) -> None:
    with pytest.raises(ValueError):
        fields(buf)


def test_every_prefix_of_the_fixture_is_a_value_error_or_readable() -> None:
    body = FIXTURE.read_bytes()[5:]  # skip the first gRPC frame header: the rest is a protobuf message
    payload = body[: struct.unpack(">I", FIXTURE.read_bytes()[1:5])[0]]
    for n in range(len(payload)):
        with contextlib.suppress(ValueError):  # an IndexError or anything else would fail the test
            fields(payload[:n])
