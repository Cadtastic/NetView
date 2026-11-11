from __future__ import annotations

import pytest
from netview_local_plugins.roku.settings import RokuSettings
from pydantic import ValidationError


def test_settings_defaults_and_bounds() -> None:
    s = RokuSettings()
    assert (s.auto_scan, s.scan_every_h, s.scan_timeout_s, s.status_interval_s, s.request_timeout_s) == (
        "startup_and_every",
        6,
        2,
        10,
        2,
    )
    for bad in (
        {"auto_scan": "daily"},
        {"scan_every_h": 0},
        {"scan_every_h": 169},
        {"scan_timeout_s": 0.4},
        {"scan_timeout_s": 10.1},
        {"status_interval_s": 4},
        {"status_interval_s": 301},
        {"request_timeout_s": 0.4},
        {"request_timeout_s": 11},
    ):
        with pytest.raises(ValidationError):
            RokuSettings(**bad)


def test_settings_schema_groups_and_titles() -> None:
    props = RokuSettings.model_json_schema()["properties"]
    assert props["scan_every_h"]["group"] == "Scanning"
    assert props["scan_every_h"]["show_when"] == {"auto_scan": "startup_and_every"}
    assert props["auto_scan"]["group"] == "Scanning"
    assert props["scan_timeout_s"]["group"] == "Scanning"
    assert props["status_interval_s"]["group"] == "Live status"
    assert props["request_timeout_s"]["group"] == "Live status"
    for p in props.values():
        assert p["title"] and p["description"]


def test_auto_scan_schema_carries_option_labels() -> None:
    prop = RokuSettings.model_json_schema()["properties"]["auto_scan"]
    assert prop["enum_labels"] == {
        "never": "Never",
        "startup": "When NetView starts",
        "startup_and_every": "When NetView starts, then on a schedule",
    }
