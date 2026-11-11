"""DNS message building and parsing, shared by the mDNS probe. Ported from LM 593-666."""

import socket
import struct

from netview.application.ports.probes import DnsRecord

MAX_POINTER_HOPS = 30
_UNICAST_RESPONSE = 0x8000
_CLASS_IN = 1


def build_query(tid: int, qname: str, qtype: int, unicast_response: bool) -> bytes:
    """One question, no answers. ``unicast_response`` sets the mDNS QU bit on the class."""
    labels = [part for part in qname.split(".") if part]
    encoded = b"".join(bytes([len(part)]) + part.encode("ascii") for part in (_checked(p) for p in labels))
    qclass = _CLASS_IN | (_UNICAST_RESPONSE if unicast_response else 0)
    header = struct.pack(">HHHHHH", tid & 0xFFFF, 0, 1, 0, 0, 0)
    return header + encoded + b"\0" + struct.pack(">HH", qtype, qclass)


def _checked(label: str) -> str:
    if not 1 <= len(label) <= 63 or not label.isascii():
        raise ValueError(f"bad DNS label {label!r}")
    return label


def _byte(data: bytes, off: int) -> int:
    if off < 0 or off >= len(data):
        raise ValueError("truncated DNS message")
    return data[off]


def _slice(data: bytes, start: int, end: int) -> bytes:
    if start < 0 or end > len(data) or start > end:
        raise ValueError("truncated DNS message")
    return data[start:end]


def _read_name(data: bytes, off: int) -> tuple[str, int]:
    """Return ``(name, offset after the name)``; follows compression pointers, at most 30 hops."""
    labels: list[str] = []
    end: int | None = None
    hops = 0
    while True:
        n = _byte(data, off)
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            if end is None:
                end = off + 2
            off = ((n & 0x3F) << 8) | _byte(data, off + 1)
            hops += 1
            if hops > MAX_POINTER_HOPS:
                raise ValueError("DNS name pointer loop")
            continue
        if n & 0xC0:
            raise ValueError("bad DNS label")
        labels.append(_slice(data, off + 1, off + 1 + n).decode("utf-8", errors="replace"))
        off += 1 + n
    return ".".join(labels), (end if end is not None else off)


def parse_records(data: bytes) -> list[DnsRecord]:
    """Every answer, authority and additional record of a DNS message.

    Raises ``ValueError`` (never ``IndexError`` or ``struct.error``) on truncated data or a
    compression-pointer loop, so a hostile reply cannot crash the caller.
    """
    try:
        return _parse(data)
    except (struct.error, IndexError) as exc:  # belt and braces: every read above is bounds-checked
        raise ValueError("malformed DNS message") from exc


def _parse(data: bytes) -> list[DnsRecord]:
    qd, an, ns, ar = struct.unpack(">HHHH", _slice(data, 4, 12))
    off = 12
    records: list[DnsRecord] = []
    for _ in range(qd):
        off = _read_name(data, off)[1] + 4
    for _ in range(an + ns + ar):
        name, off = _read_name(data, off)
        rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", _slice(data, off, off + 10))
        off += 10
        start, end = off, off + rdlen
        _slice(data, start, end)  # the record data must fit in the message
        off = end
        value: str | tuple[str, ...] | None = None
        if rtype in (5, 12):
            value = _read_name(data, start)[0]
        elif rtype == 1 and rdlen == 4:
            value = socket.inet_ntoa(data[start:end])
        elif rtype == 16:
            strings: list[str] = []
            pos = start
            while pos < end:
                length = data[pos]
                strings.append(
                    _slice(data, pos + 1, min(pos + 1 + length, end)).decode("utf-8", errors="replace")
                )
                pos += 1 + length
            value = tuple(strings)
        elif rtype == 33:
            port = struct.unpack(">H", _slice(data, start + 4, start + 6))[0]
            value = f"{_read_name(data, start + 6)[0]}:{port}"
        records.append(DnsRecord(name, rtype, value))
    return records
