from typing import Any

import pytest

from netview.application.plugins.plugin_json import parse_plugin_json, plugin_json_to_dict
from netview.domain.errors import ValidationError


def _good() -> dict[str, Any]:
    return {
        "schema": "netview.plugin/1",
        "id": "gsm7248",
        "name": "NETGEAR GSM7248",
        "version": "0.1.0",
        "description": "Ports, VLANs and traffic for the GSM7248 switch over SNMP",
        "author": "Cadtastic",
        "homepage": "https://github.com/Cadtastic/NetView/tree/main/plugins/gsm7248",
        "sdk_version": ">=1.3,<2",
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
    assert pj.id == "gsm7248"
    assert pj.license is None
    assert pj.capabilities == ("api", "jobs", "storage", "web_ui")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "netview.plugin/2"),
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
