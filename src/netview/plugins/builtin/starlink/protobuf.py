"""A minimal, strict protobuf reader (ported from the old LAN monitor, LM 1061-1090).

Unlike the original, truncated input and unknown wire types raise ``ValueError``; nothing here raises
``IndexError`` or silently returns a short slice.
"""

from __future__ import annotations

_MAX_VARINT_BITS = 70  # a varint is at most 10 bytes


def varint(buf: bytes, i: int) -> tuple[int, int]:
    """Read a varint at ``buf[i]``: ``(value, index after it)``."""
    n = shift = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated protobuf varint")
        c = buf[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return n, i
        if shift >= _MAX_VARINT_BITS:
            raise ValueError("protobuf varint is too long")


def _take(buf: bytes, i: int, length: int) -> tuple[bytes, int]:
    if length < 0 or i + length > len(buf):
        raise ValueError("truncated protobuf field")
    return buf[i : i + length], i + length


def fields(buf: bytes) -> dict[int, list[int | bytes]]:
    """``{field number: [values]}``: ints for varints, bytes for everything else."""
    out: dict[int, list[int | bytes]] = {}
    i = 0
    while i < len(buf):
        key, i = varint(buf, i)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("protobuf field number 0")
        value: int | bytes
        if wire == 0:
            value, i = varint(buf, i)
        elif wire == 1:
            value, i = _take(buf, i, 8)
        elif wire == 5:
            value, i = _take(buf, i, 4)
        elif wire == 2:
            length, i = varint(buf, i)
            value, i = _take(buf, i, length)
        else:
            raise ValueError("unsupported protobuf wire type")
        out.setdefault(number, []).append(value)
    return out
