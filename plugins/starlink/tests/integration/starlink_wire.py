"""Builds a synthetic gRPC-Web ``wifi_get_clients`` answer. Documentation addresses only, not a capture.

Run ``python starlink_wire.py`` to rewrite ``../fixtures/clients.bin``.
"""

from __future__ import annotations

import struct
from pathlib import Path

FIXTURE = Path(__file__).parents[1] / "fixtures" / "clients.bin"


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        low = n & 0x7F
        n >>= 7
        out.append(low | (0x80 if n else 0))
        if not n:
            return bytes(out)


def vfield(number: int, value: int) -> bytes:
    return varint(number << 3) + varint(value)


def lfield(number: int, value: bytes | str) -> bytes:
    raw = value.encode() if isinstance(value, str) else value
    return varint(number << 3 | 2) + varint(len(raw)) + raw


def ffield(number: int, value: float) -> bytes:
    return varint(number << 3 | 5) + struct.pack("<f", value)


def client(
    ip: str | None,
    name: str = "",
    down: int | None = None,
    up: int | None = None,
    signal: float | None = None,
    role: int | None = None,
    assoc_s: int | None = None,
    ap: str = "",
    down_link: int | None = None,
    up_link: int | None = None,
) -> bytes:
    """One entry of the client list (field 1 of the answer)."""
    out = b""
    if name:
        out += lfield(1, name)
    if ip:
        out += lfield(3, ip)
    if signal is not None:
        out += ffield(4, signal)
    if down is not None:
        out += lfield(5, vfield(1, down) + (vfield(8, down_link) if down_link is not None else b""))
    if up is not None:
        out += lfield(6, vfield(1, up) + (vfield(8, up_link) if up_link is not None else b""))
    if assoc_s is not None:
        out += vfield(7, assoc_s)
    if ap:
        out += lfield(13, ap)
    if role is not None:
        out += vfield(14, role)
    return out


def frame(payload: bytes, flag: int = 0) -> bytes:
    return bytes([flag]) + struct.pack(">I", len(payload)) + payload


def response(clients: list[bytes], trailer: str = "grpc-status: 0\r\n") -> bytes:
    """A whole answer body: the data frame (field 3002 holds the list) and a trailers frame."""
    listing = b"".join(lfield(1, c) for c in clients)
    return frame(lfield(3002, listing)) + frame(trailer.encode(), flag=0x80)


def default_clients() -> list[bytes]:
    return [
        client("", name="Starlink router", down=1, up=2),  # the router's own entry has no IP
        client(
            "192.0.2.20",
            name="Living room TV",
            down=5_000_000,
            up=300_000,
            signal=-52.5,
            role=1,
            assoc_s=7200,
            ap="Kitchen",
            down_link=866,
            up_link=433,
        ),
        client("192.0.2.21", name="Hall mesh", down=9_000, up=4_000, signal=-60.0, role=2),
    ]


def default_response() -> bytes:
    return response(default_clients())


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(default_response())
    print(f"wrote {FIXTURE}")
