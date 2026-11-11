"""The Starlink router's gRPC-Web API (ported from the old LAN monitor, LM 1093-1135).

A Starlink router answers gRPC-Web on port 9001 without a login. Only the read-only ``wifi_get_clients``
request (field 3002 of ``SpaceX.API.Device.Request``) is ever sent: it returns each Wi-Fi client's name, IP,
signal and byte counters. Field numbers were checked against a live router (LM 1055-1060): ``rx_stats`` (5)
counts bytes the client downloaded, ``tx_stats`` (6) bytes it uploaded.
"""

from __future__ import annotations

import http.client
import math
import struct
from collections.abc import Callable, Mapping
from typing import Any

from .protobuf import fields

PATH = "/SpaceX.API.Device.Device/Handle"
HEADERS = {"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"}
REQUEST = bytes([0xD2, 0xBB, 0x01, 0x00])  # field 3002 (wifi_get_clients), empty message
MAX_BODY = 1 << 20
UNREADABLE = "router API sent an unreadable answer"
_ROLES = {2: "mesh node", 3: "router"}

Fields = dict[int, list[int | bytes]]
Post = Callable[[str, int, str, bytes, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


def _http_post(
    host: str, port: int, path: str, body: bytes, headers: Mapping[str, str], timeout_s: float
) -> tuple[int, Mapping[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
    try:
        conn.request("POST", path, body, dict(headers))
        response = conn.getresponse()
        data = response.read(MAX_BODY)
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data
    except http.client.HTTPException as exc:  # not an OSError, but it means the same to the caller
        raise OSError(f"router API sent a bad HTTP answer: {type(exc).__name__}") from exc
    finally:
        conn.close()


def _refused(status: int, message: str) -> OSError:
    return OSError(f"router API refused: HTTP {status} {message}".strip())


def _frames(data: bytes) -> list[tuple[int, bytes]]:
    """The gRPC-Web frames of a body: ``(flag, payload)``. A frame that runs past the body is an error."""
    out: list[tuple[int, bytes]] = []
    i = 0
    while i < len(data):
        if i + 5 > len(data):
            raise ValueError("truncated gRPC frame header")
        flag = data[i]
        (length,) = struct.unpack(">I", data[i + 1 : i + 5])
        end = i + 5 + length
        if end > len(data):
            raise ValueError("truncated gRPC frame")
        out.append((flag, data[i + 5 : end]))
        i = end
    return out


def _trailer(payload: bytes) -> dict[str, str]:
    text = payload.decode("utf-8", errors="replace")
    pairs = (line.split(":", 1) for line in text.splitlines() if ":" in line)
    return {k.strip().lower(): v.strip() for k, v in pairs}


def _sub(f: Fields, key: int) -> Fields:
    value = f.get(key, [None])[0]
    return fields(value) if isinstance(value, bytes) else {}


def _text(f: Fields, key: int) -> str:
    value = f.get(key, [None])[0]
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else ""


def _int(f: Fields, key: int) -> int | None:
    value = f.get(key, [None])[0]
    return value if isinstance(value, int) else None


def _signal(f: Fields) -> float | None:
    raw = f.get(4, [None])[0]
    if not isinstance(raw, bytes) or len(raw) != 4:
        return None
    (value,) = struct.unpack("<f", raw)
    return round(value, 1) if math.isfinite(value) else None


def _parse(data: bytes) -> list[dict[str, Any]]:
    payload: bytes | None = None
    for flag, body in _frames(data):
        if flag & 0x80:  # trailers: a gRPC error can arrive here instead of in the HTTP headers
            trailer = _trailer(body)
            code = trailer.get("grpc-status")
            if code not in (None, "0"):
                raise _refused(200, trailer.get("grpc-message") or f"grpc-status {code}")
        elif payload is None:
            payload = body
    response = fields(payload or b"").get(3002)
    if not response:
        raise OSError("router API sent no client list")
    first = response[0]
    if not isinstance(first, bytes):
        raise ValueError("client list is not a message")
    out: list[dict[str, Any]] = []
    for raw in fields(first).get(1, []):
        if not isinstance(raw, bytes):
            continue
        f = fields(raw)
        ip = _text(f, 3)
        if not ip:
            continue  # the router's own entry
        rx, tx = _sub(f, 5), _sub(f, 6)
        # proto3 leaves out a zero: a stats message that is there without field 1 counted 0 bytes. Only a
        # client with no stats message at all has no counters.
        down = (_int(rx, 1) or 0) if 5 in f else None
        up = (_int(tx, 1) or 0) if 6 in f else None
        role = f.get(14, [1])[0]
        out.append(
            {
                "ip": ip,
                "name": _text(f, 1)[:60],
                "ap": _text(f, 13),
                "signal": _signal(f),
                "down_bytes": down,
                "up_bytes": up,
                "down_link": _int(rx, 8),
                "up_link": _int(tx, 8),
                "assoc_s": _int(f, 7),
                "role": _ROLES.get(role, "client") if isinstance(role, int) else "client",
            }
        )
    return out


def starlink_clients(
    host: str, port: int = 9001, timeout_s: float = 4.0, post: Post = _http_post
) -> list[dict[str, Any]]:
    """Read-only: the router's Wi-Fi client list with traffic counters.

    Raises ``OSError`` when the router cannot be reached or refuses, and ``ValueError`` when what it sent
    cannot be read.
    """
    body = b"\x00" + struct.pack(">I", len(REQUEST)) + REQUEST
    status, headers, data = post(host, port, PATH, body, HEADERS, timeout_s)
    lowered = {str(k).lower(): v for k, v in headers.items()}
    code = lowered.get("grpc-status")
    if status != 200 or code not in (None, "0"):
        message = lowered.get("grpc-message") or (f"grpc-status {code}" if code not in (None, "0") else "")
        raise _refused(status, message)
    try:
        return _parse(data)
    except (ValueError, struct.error, IndexError, OverflowError) as exc:  # UnicodeError is a ValueError
        raise ValueError(UNREADABLE) from exc
