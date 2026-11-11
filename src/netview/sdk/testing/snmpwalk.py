"""Parse net-snmp ``snmpwalk -On`` text into rows, for fixtures."""

from __future__ import annotations

import re

from netview.application.ports.snmp import Oid, SnmpValue, parse_oid

_LINE = re.compile(r"^(\.?\d+(?:\.\d+)*)\s*=\s*(.*)$", re.DOTALL)
_TYPED = re.compile(r"^([A-Za-z0-9-]+):\s*(.*)$", re.DOTALL)
_NAMED_INT = re.compile(r"^(?:[^()]*\()?(-?\d+)\)?\b")
_TICKS = re.compile(r"^\((\d+)\)")
_HEX_CONTINUATION = re.compile(r"^\s*([0-9A-Fa-f]{2}\s*)+$")
_HEX_RECORD = re.compile(r"^[^=]*=\s*Hex-STRING:", re.DOTALL)


def _unquote(text: str) -> bytes:
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text.encode("utf-8")


def _value(raw: str) -> SnmpValue:
    raw = raw.strip()
    if raw.startswith('"'):
        return _unquote(raw)
    typed = _TYPED.match(raw)
    if typed is None:
        return b"" if raw == "" else raw.encode("utf-8")
    kind, body = typed.group(1), typed.group(2).strip()
    if kind == "STRING":
        return _unquote(body)
    if kind == "Hex-STRING":
        return bytes.fromhex("".join(body.split()))
    if kind == "INTEGER":
        m = _NAMED_INT.match(body)
        if m is None:
            raise ValueError(f"bad INTEGER value: {body!r}")
        return int(m.group(1))
    if kind in ("Counter32", "Counter64", "Gauge32", "Unsigned32"):
        return int(body.split()[0])
    if kind == "Timeticks":
        m = _TICKS.match(body)
        if m is None:
            raise ValueError(f"bad Timeticks value: {body!r}")
        return int(m.group(1))
    if kind == "OID":
        return parse_oid(body)
    if kind == "IpAddress":
        return body
    raise ValueError(f"unsupported value type {kind!r}")


def parse_snmpwalk(text: str) -> list[tuple[Oid, SnmpValue]]:
    """Rows in file order.

    A quoted string or a Hex-STRING may span lines; blank and ``#`` comment lines are skipped.
    """
    records: list[str] = []
    for line in text.splitlines():
        open_quote = bool(records) and records[-1].count('"') % 2 == 1
        if open_quote:
            records[-1] += "\n" + line
        elif line.strip().startswith("#"):
            continue
        elif records and _HEX_RECORD.match(records[-1]) and _HEX_CONTINUATION.match(line):
            records[-1] += " " + line.strip()
        elif line.strip():
            records.append(line)
    rows: list[tuple[Oid, SnmpValue]] = []
    for record in records:
        if not record.strip():
            continue
        m = _LINE.match(record)
        if m is None:
            raise ValueError(f"not an snmpwalk line: {record!r}")
        rows.append((parse_oid(m.group(1)), _value(m.group(2))))
    return rows
