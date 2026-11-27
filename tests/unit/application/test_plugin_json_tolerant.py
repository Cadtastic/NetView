import logging
from typing import Any

import pytest

from netview.application.plugins.manifest import SDK_VERSION
from netview.application.plugins.plugin_json import INDEX_SCHEMA, installable, parse_index, parse_plugin_json
from netview.domain.errors import ValidationError

_GUID_A = "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4"
_GUID_B = "4be5ddcb-5e96-4dcc-b439-7b582a37b0f4"


def _plugin(guid: str = _GUID_A, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": "netview.plugin/2",
        "name": "Thing",
        "version": "0.1.0",
        "description": "d",
        "guid": guid,
        "display_name": "Thing",
        "plugin_type": "other",
        "sdk_version": ">=2.0,<3",
        "capabilities": ["api"],
        "permissions": ["api"],
    }
    data.update(over)
    return data


def _index(*entries: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": INDEX_SCHEMA,
        "ref": "main",
        "archive_url": "https://example.com/a.zip",
        "plugins": [{**e, "path": f"plugins/{e['name'].lower()}"} for e in entries],
    }


def test_unknown_permission_in_index_keeps_the_list() -> None:
    index = parse_index(
        _index(
            _plugin(_GUID_A, name="Alpha"),
            _plugin(_GUID_B, name="Beta", permissions=["api", "network:teleport"]),
        )
    )
    assert len(index.plugins) == 2
    second = index.plugins[1]
    assert second.plugin.unsupported == ("permissions:network:teleport",)
    assert installable(second.plugin, "2.1", lambda n: True) == "Needs a newer netview"
    assert installable(index.plugins[0].plugin, "2.1", lambda n: True) is None


def test_unknown_capability_and_plugin_type_are_unsupported_not_fatal() -> None:
    index = parse_index(
        _index(_plugin(name="Alpha", capabilities=["api", "quantum"], plugin_type="spaceship"))
    )
    pj = index.plugins[0].plugin
    assert set(pj.unsupported) == {"capabilities:quantum", "plugin_type:spaceship"}
    assert installable(pj, "2.1", lambda n: True) == "Needs a newer netview"


def test_malformed_entry_is_dropped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    bad = _plugin(_GUID_B, name="Beta")
    del bad["guid"]
    with caplog.at_level(logging.WARNING):
        index = parse_index(_index(_plugin(name="Alpha"), bad))
    assert [e.plugin.name for e in index.plugins] == ["Alpha"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "plugins/beta" in warnings[0].getMessage()


def test_local_plugin_json_stays_strict() -> None:
    with pytest.raises(ValidationError):
        parse_plugin_json(_plugin(permissions=["api", "network:teleport"]))


def test_network_internet_is_known() -> None:
    assert parse_plugin_json(_plugin(permissions=["api", "network:internet"])).unsupported == ()


def test_duplicate_guid_still_rejects_the_index() -> None:
    with pytest.raises(ValidationError):
        parse_index(_index(_plugin(_GUID_A, name="Alpha"), _plugin(_GUID_A, name="Beta")))


def test_sdk_version_is_2_1() -> None:
    assert SDK_VERSION == "2.1"
