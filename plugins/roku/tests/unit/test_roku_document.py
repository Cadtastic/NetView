from __future__ import annotations

import json
import time
from collections.abc import Callable
from itertools import count

import pytest
from netview_local_plugins.roku.document import (
    SCHEMA,
    DocumentError,
    MergeHits,
    MergeIps,
    Replace,
    parse_document,
    to_document,
    validate_replace,
)
from netview_local_plugins.roku.model import FIELDS, SavedTv

NOW = "2026-11-11T15:00:00Z"


def _ids() -> Callable[[], str]:
    c = count(1)
    return lambda: f"n{next(c)}"


def test_parse_replace_document() -> None:
    text = json.dumps({"schema": SCHEMA, "tvs": [{"ip": "192.168.1.60"}]})
    assert parse_document(text) == Replace([{"ip": "192.168.1.60"}])


@pytest.mark.parametrize("schema", ["ketiv.network-tools/roku-scan@1", "roku-scan@1"])
def test_parse_find_rokus_output_both_schema_ids(schema: str) -> None:
    dev = {
        "ip": "192.168.1.60", "name": "Lounge", "model": "7000X", "location": "http://x", "tv": False,
        "mode": "default", "power": "PowerOn", "found_by": "ssdp+sweep",
    }  # fmt: skip
    r = parse_document(json.dumps({"schema": schema, "subnet": "192.168.1.0/24", "devices": [dev]}))
    assert isinstance(r, MergeHits) and len(r.hits) == 1
    h = r.hits[0]
    assert (h.ip, h.serial, h.name, h.tv, h.found_by) == ("192.168.1.60", "", "Lounge", False, "ssdp+sweep")


def test_parse_powershell_array() -> None:
    r = parse_document(json.dumps([{"ip": "192.168.1.60", "name": "A"}, {"ip": "10.0.0.5"}]))
    assert isinstance(r, MergeHits) and [h.ip for h in r.hits] == ["192.168.1.60", "10.0.0.5"]
    assert r.hits[0].found_by == "manual" and r.hits[0].tv is True


def test_parse_ip_lines() -> None:
    assert parse_document("192.168.1.60\n\n192.168.1.61\n") == MergeIps(["192.168.1.60", "192.168.1.61"])


def test_parse_ignores_text_around_json() -> None:
    text = (
        '>>> ran\n{"schema": "roku-scan@1", "devices": [{"ip": "192.168.1.60"}]}\n'
        "Found 1 Roku device (subnet ...)."
    )
    assert isinstance(parse_document(text), MergeHits)


def test_parse_refuses_public_address() -> None:
    with pytest.raises(DocumentError, match=r"8.8.8.8 is not a private address"):
        parse_document("8.8.8.8")
    with pytest.raises(DocumentError, match=r"8.8.8.8 is not a private address"):
        parse_document(json.dumps([{"ip": "8.8.8.8"}]))


@pytest.mark.parametrize("text", ["hello", "", "{}", "[1, 2]", '{"schema": "other"}', "5"])
def test_parse_refuses_garbage(text: str) -> None:
    with pytest.raises(DocumentError, match="Not a TV list, scan output or list of addresses"):
        parse_document(text)


def test_replace_refuses_unknown_field() -> None:
    with pytest.raises(DocumentError) as e:
        validate_replace([{"ip": "192.168.1.60", "power": "on"}], _ids(), NOW)
    assert e.value.message == "Unknown field 'power' in TV 1"


@pytest.mark.parametrize("field", ["id", "ip", "serial"])
def test_replace_refuses_duplicates(field: str) -> None:
    a = {"id": "a", "ip": "192.168.1.60", "serial": "S1"}
    b = {"id": "b", "ip": "192.168.1.61", "serial": "S2"}
    b[field] = a[field]
    with pytest.raises(DocumentError) as e:
        validate_replace([a, b], _ids(), NOW)
    assert e.value.message == f"TV 2 repeats the {field} of TV 1"


def test_replace_allows_repeated_empty_serials() -> None:
    assert len(validate_replace([{"ip": "192.168.1.60"}, {"ip": "192.168.1.61"}], _ids(), NOW)) == 2


def test_replace_assigns_missing_ids_and_defaults() -> None:
    entries = [{"ip": "192.168.1.60"}, {"id": "keep", "ip": "192.168.1.61", "tv": False}]
    tvs = validate_replace(entries, _ids(), NOW)
    assert [t.id for t in tvs] == ["n1", "keep"]
    t = tvs[0]
    assert (t.serial, t.name, t.label, t.tv, t.first_seen, t.last_seen) == ("", "", "", True, NOW, NOW)
    assert tvs[1].tv is False


def test_replace_requires_ip_private_and_short_label() -> None:
    with pytest.raises(DocumentError):
        validate_replace([{"name": "x"}], _ids(), NOW)
    with pytest.raises(DocumentError, match="not a private address"):
        validate_replace([{"ip": "1.2.3.4"}], _ids(), NOW)
    with pytest.raises(DocumentError, match="60"):
        validate_replace([{"ip": "192.168.1.60", "label": "x" * 61}], _ids(), NOW)
    assert validate_replace([{"ip": "192.168.1.60", "label": "x" * 60}], _ids(), NOW)


def test_to_document_round_trips() -> None:
    tv = SavedTv("a", "S1", "192.168.1.60", "N", "L", "M", "loc", True, "ssdp", NOW, NOW)
    doc = to_document([tv])
    assert doc["schema"] == SCHEMA and list(doc["tvs"][0]) == list(FIELDS)
    parsed = parse_document(json.dumps(doc))
    assert isinstance(parsed, Replace)
    assert validate_replace(parsed.tvs, _ids(), "later") == [tv]
    assert tv.title == "L"


def test_deeply_nested_input_is_garbage_not_a_crash() -> None:
    with pytest.raises(DocumentError, match="Not a TV list, scan output or list of addresses"):
        parse_document("[" * 100000)


@pytest.mark.parametrize("opener", ["[", '{"a":', "[{"])
def test_deeply_nested_input_is_refused_quickly(opener: str) -> None:
    started = time.monotonic()
    with pytest.raises(DocumentError, match="Not a TV list, scan output or list of addresses"):
        parse_document(opener * 50000)
    assert time.monotonic() - started < 1.0


def test_text_over_one_megabyte_is_refused_up_front() -> None:
    with pytest.raises(DocumentError) as err:
        parse_document(" " * 1_000_001)
    assert err.value.message == "The text is too long (over 1 MB)"
    with pytest.raises(DocumentError, match="Not a TV list"):
        parse_document(" " * 1_000_000)


@pytest.mark.parametrize("bad", ["a/b", "a b", "a?b", "x" * 33, "..", "\u00e9"])
def test_replace_refuses_ids_that_cannot_be_used_in_a_path(bad: str) -> None:
    with pytest.raises(DocumentError) as e:
        validate_replace([{"ip": "192.168.1.60"}, {"id": bad, "ip": "192.168.1.61"}], _ids(), NOW)
    assert e.value.message == "TV 2 has an id that is not letters, digits, - or _"


def test_replace_accepts_ids_made_of_letters_digits_dash_underscore() -> None:
    entries = [{"id": "Ab_9-z", "ip": "192.168.1.60"}, {"id": "x" * 32, "ip": "192.168.1.61"}]
    assert [t.id for t in validate_replace(entries, _ids(), NOW)] == ["Ab_9-z", "x" * 32]


def test_generated_ids_are_valid_ids() -> None:
    import re

    from netview_local_plugins.roku.service import RokuService

    assert re.fullmatch(r"[A-Za-z0-9_-]{1,32}", RokuService._new_id())


def test_json_after_a_few_stray_brackets_is_still_found() -> None:
    text = "see [x] and {note} then " + json.dumps({"schema": SCHEMA, "tvs": []})
    assert isinstance(parse_document(text), Replace)
