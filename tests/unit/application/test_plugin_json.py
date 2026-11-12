from typing import Any

import pytest

from netview.application.plugins.plugin_json import parse_plugin_json, plugin_json_to_dict
from netview.domain.errors import ValidationError


def _good() -> dict[str, Any]:
    return {
        "schema": "netview.plugin/2",
        "name": "NETGEAR GSM7248",
        "version": "0.1.0",
        "description": "Ports, VLANs and traffic for the GSM7248 switch over SNMP",
        "guid": "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4",
        "display_name": "GSM7248",
        "plugin_type": "switch",
        "author": "Cadtastic",
        "homepage": "https://github.com/Cadtastic/NetView/tree/main/plugins/gsm7248",
        "sdk_version": ">=2.0,<3",
        "capabilities": ["api", "web_ui", "storage", "jobs"],
        "permissions": [
            "api",
            "devices:read",
            "names:write",
            "network:probe",
            "storage:own",
            "types:write",
            "ui",
        ],
        "requires": [],
    }


def test_parse_minimal_plugin_json() -> None:
    pj = parse_plugin_json(_good())
    assert pj.name == "NETGEAR GSM7248"
    assert pj.license is None
    assert pj.capabilities == ("api", "jobs", "storage", "web_ui")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "netview.plugin/1"),
        ("id", "Bad-Id"),
        ("id", "gsm\n"),
        ("capabilities", ["teleport"]),
        ("sdk_version", ">>1"),
    ],
)
def test_parse_rejects_bad_field(field: str, value: object) -> None:
    data = _good()
    data[field] = value
    with pytest.raises(ValidationError):
        parse_plugin_json(data)


def test_parse_rejects_wrong_schema() -> None:
    data = _good()
    del data["schema"]
    with pytest.raises(ValidationError):
        parse_plugin_json(data)


def test_parse_rejects_non_object() -> None:
    with pytest.raises(ValidationError):
        parse_plugin_json([])


def test_round_trip() -> None:
    pj = parse_plugin_json(_good())
    assert parse_plugin_json(plugin_json_to_dict(pj)) == pj


@pytest.mark.parametrize("field", ["guid", "display_name", "plugin_type"])
def test_plugin_json_requires_new_fields(field: str) -> None:
    data = _good()
    del data[field]
    with pytest.raises(ValidationError, match=field):
        parse_plugin_json(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [("plugin_type", "toaster"), ("guid", "ABC"), ("guid", "4EDDF684-DEB5-41CF-9588-020746307ADE")],
)
def test_plugin_json_rejects_bad_new_field(field: str, value: str) -> None:
    data = _good()
    data[field] = value
    with pytest.raises(ValidationError, match=field):
        parse_plugin_json(data)


def test_plugin_json_round_trip_new_fields() -> None:
    pj = parse_plugin_json(_good())
    out = plugin_json_to_dict(pj)
    assert (out["guid"], out["display_name"], out["plugin_type"]) == (
        "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4",
        "GSM7248",
        "switch",
    )
    keys = list(out)
    assert keys[keys.index("description") + 1 : keys.index("description") + 4] == [
        "guid",
        "display_name",
        "plugin_type",
    ]
    assert parse_plugin_json(out) == pj


def test_plugin_json_v2_has_no_id() -> None:
    data = _good()
    data["id"] = "gsm7248"
    with pytest.raises(ValidationError, match="unknown field id"):
        parse_plugin_json(data)


def test_plugin_json_rejects_any_unknown_field() -> None:
    data = _good()
    data["colour"] = "red"
    with pytest.raises(ValidationError, match="unknown field colour"):
        parse_plugin_json(data)


def test_schema_ids_are_2() -> None:
    assert _good()["schema"] == "netview.plugin/2"
    assert "id" not in plugin_json_to_dict(parse_plugin_json(_good()))
