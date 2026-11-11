"""The saved list as a JSON document, and parsing of everything that may be pasted or uploaded."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from .addresses import is_allowed_ip
from .model import FIELDS, SavedTv, ScanHit

SCHEMA = "netview.roku/tvs@1"
_SCAN_SCHEMAS = ("ketiv.network-tools/roku-scan@1", "roku-scan@1")
_GARBAGE = "Not a TV list, scan output or list of addresses"
_MAX_LABEL = 60
_MAX_TEXT = 1_000_000
_MAX_JSON_STARTS = 200  # a failed attempt costs time proportional to the text, so cap how many are made
_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
_TEXT_FIELDS = tuple(f for f in FIELDS if f != "tv")


class DocumentError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Replace:
    tvs: list[dict[str, Any]]


@dataclass(frozen=True)
class MergeHits:
    hits: list[ScanHit]


@dataclass(frozen=True)
class MergeIps:
    ips: list[str]


def to_document(tvs: list[SavedTv]) -> dict[str, Any]:
    return {"schema": SCHEMA, "tvs": [asdict(tv) for tv in tvs]}


def _load_json(text: str) -> Any:
    """The JSON value in ``text``, ignoring any text before and after it; None when there is none."""
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        value = None
    if isinstance(value, dict | list):
        return value
    decoder = json.JSONDecoder()
    starts = 0
    for i, ch in enumerate(text):
        if ch in "{[":
            starts += 1
            if starts > _MAX_JSON_STARTS:
                return None
            try:
                value, _ = decoder.raw_decode(text, i)
            except RecursionError:
                return None  # nested too deeply; every later start would cost as much again
            except ValueError:
                continue
            if isinstance(value, dict | list):
                return value
    return None


def _ip_lines(text: str) -> list[str] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    for line in lines:
        try:
            ipaddress.IPv4Address(line)
        except ValueError:
            return None
    return lines


def _check_ip(ip: str) -> str:
    if not is_allowed_ip(ip):
        raise DocumentError(f"{ip} is not a private address")
    return ip


def _hits(entries: Any) -> MergeHits:
    if not isinstance(entries, list):
        raise DocumentError(_GARBAGE)
    hits = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("ip"), str):
            raise DocumentError(_GARBAGE)
        hits.append(
            ScanHit(
                ip=_check_ip(entry["ip"]),
                serial=str(entry.get("serial") or ""),
                name=str(entry.get("name") or ""),
                model=str(entry.get("model") or ""),
                location=str(entry.get("location") or ""),
                tv=entry.get("tv") is not False,
                found_by=str(entry.get("found_by") or "manual"),
            )
        )
    return MergeHits(hits)


def parse_document(text: str) -> Replace | MergeHits | MergeIps:
    if len(text) > _MAX_TEXT:
        raise DocumentError("The text is too long (over 1 MB)")
    ips = _ip_lines(text)
    if ips is not None:
        return MergeIps([_check_ip(ip) for ip in ips])
    value = _load_json(text)
    if isinstance(value, dict):
        schema = value.get("schema")
        if schema == SCHEMA and isinstance(value.get("tvs"), list):
            return Replace(value["tvs"])
        if schema in _SCAN_SCHEMAS:
            return _hits(value.get("devices"))
    elif isinstance(value, list) and value and all(isinstance(e, dict) and "ip" in e for e in value):
        return _hits(value)
    raise DocumentError(_GARBAGE)


def validate_replace(entries: list[dict[str, Any]], new_id: Callable[[], str], now_iso: str) -> list[SavedTv]:
    prepared: list[dict[str, Any]] = []
    for n, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise DocumentError(f"TV {n} is not an object")
        for key in entry:
            if key not in FIELDS:
                raise DocumentError(f"Unknown field '{key}' in TV {n}")
        ip = entry.get("ip")
        if not isinstance(ip, str) or not ip:
            raise DocumentError(f"TV {n} has no ip")
        _check_ip(ip)
        for key in _TEXT_FIELDS:
            if key in entry and not isinstance(entry[key], str):
                raise DocumentError(f"Field '{key}' of TV {n} must be text")
        if "tv" in entry and not isinstance(entry["tv"], bool):
            raise DocumentError(f"Field 'tv' of TV {n} must be true or false")
        if len(entry.get("label", "")) > _MAX_LABEL:
            raise DocumentError(f"Label of TV {n} is longer than {_MAX_LABEL} characters")
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id and not _ID.fullmatch(entry_id):
            raise DocumentError(f"TV {n} has an id that is not letters, digits, - or _")
        for field in ("id", "serial"):  # an address may repeat: a reshuffle can leave a stale entry on it
            value = entry.get(field)
            if not value:
                continue
            for m, earlier in enumerate(prepared, start=1):
                if earlier.get(field) == value:
                    raise DocumentError(f"TV {n} repeats the {field} of TV {m}")
        prepared.append(entry)
    tvs = []
    for entry in prepared:
        values: dict[str, Any] = {"tv": True, "first_seen": now_iso, "last_seen": now_iso}
        values.update({k: "" for k in _TEXT_FIELDS if k not in ("first_seen", "last_seen")})
        values.update(entry)
        if not values["id"]:
            values["id"] = new_id()
        for stamp in ("first_seen", "last_seen"):
            values[stamp] = values[stamp] or now_iso
        tvs.append(SavedTv(**values))
    return tvs
