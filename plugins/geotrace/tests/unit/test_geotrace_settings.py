from __future__ import annotations

import json
from pathlib import Path

import pytest
from netview_local_plugins.geotrace.plugin import GeoTracePlugin
from netview_local_plugins.geotrace.settings import GeoTraceSettings
from pydantic import ValidationError

PLUGIN_JSON = Path(__file__).resolve().parents[2] / "plugin.json"


def test_defaults() -> None:
    s = GeoTraceSettings()
    assert (s.home_label, s.home_lat, s.home_lon) == ("", None, None)
    assert (s.retention_days, s.default_interval_min, s.default_family) == (90, 15, "ipv4")
    assert (s.tile_source, s.custom_tile_url, s.base_imagery, s.tile_cache_mb) == (
        "osm",
        "",
        "natural_earth",
        500,
    )
    assert s.geo_auto_update is True


@pytest.mark.parametrize(
    "bad",
    [
        {"home_lat": 90.1},
        {"home_lat": -90.1},
        {"home_lon": 180.1},
        {"home_lon": -180.1},
        {"retention_days": 6},
        {"retention_days": 3651},
        {"default_interval_min": 10},
        {"default_family": "ipv5"},
        {"tile_source": "bing"},
        {"base_imagery": "mapbox"},
        {"tile_cache_mb": 49},
        {"tile_cache_mb": 20001},
    ],
)
def test_bounds(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GeoTraceSettings(**bad)  # type: ignore[arg-type]


def test_bounds_accept_the_edges() -> None:
    s = GeoTraceSettings(home_lat=-90, home_lon=180, retention_days=7, tile_cache_mb=20000)
    assert (s.home_lat, s.home_lon, s.retention_days, s.tile_cache_mb) == (-90, 180, 7, 20000)
    assert GeoTraceSettings(retention_days=3650, tile_cache_mb=50).retention_days == 3650


@pytest.mark.parametrize(
    "url",
    ["", "http://x/{z}/{x}/{y}", "https://x/{z}/{x}", "https://x/{z}/{y}", "https://x/{x}/{y}"],
)
def test_custom_tile_url_must_be_https_with_placeholders(url: str) -> None:
    with pytest.raises(ValidationError):
        GeoTraceSettings(tile_source="custom", custom_tile_url=url)


def test_custom_tile_url_accepted() -> None:
    s = GeoTraceSettings(tile_source="custom", custom_tile_url="https://t.example/{z}/{x}/{y}.png")
    assert s.custom_tile_url == "https://t.example/{z}/{x}/{y}.png"


def test_custom_tile_url_not_checked_for_osm() -> None:
    assert GeoTraceSettings(tile_source="osm", custom_tile_url="junk").tile_source == "osm"


def test_schema_tabs_in_order_and_fields_on_them() -> None:
    schema = GeoTraceSettings.model_json_schema()
    assert schema["tabs"] == ["General", "Map", "Location data"]
    tabs = {name: p["tab"] for name, p in schema["properties"].items()}
    assert tabs == {
        "home_label": "General",
        "home_lat": "General",
        "home_lon": "General",
        "retention_days": "General",
        "default_interval_min": "General",
        "default_family": "General",
        "tile_source": "Map",
        "custom_tile_url": "Map",
        "base_imagery": "Map",
        "tile_cache_mb": "Map",
        "geo_auto_update": "Location data",
    }


def test_schema_enum_labels_titles_and_descriptions() -> None:
    props = GeoTraceSettings.model_json_schema()["properties"]
    assert props["tile_source"]["enum_labels"] == {"osm": "OpenStreetMap", "custom": "Custom tile server"}
    assert props["base_imagery"]["enum_labels"] == {
        "natural_earth": "Natural Earth (built in)",
        "eox_s2": "Sentinel-2 cloudless (EOX, non-commercial)",
    }
    for p in props.values():
        assert p.get("title") and p.get("description")


def test_plugin_json_equals_the_manifest() -> None:
    data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    m = GeoTracePlugin.manifest
    assert data == {
        "schema": "netview.plugin/2",
        "name": m.name,
        "version": m.version,
        "description": m.description,
        "guid": m.guid,
        "display_name": m.display_name,
        "plugin_type": m.plugin_type.value,
        "author": "Cadtastic",
        "homepage": "https://github.com/Cadtastic/NetView/tree/main/plugins/geotrace",
        "sdk_version": m.sdk_version,
        "capabilities": sorted(c.value for c in m.capabilities),
        "permissions": sorted(p.value for p in m.permissions),
        "requires": [],
    }
    assert (m.name, m.display_name, m.version, m.guid, m.plugin_type.value, m.sdk_version) == (
        "GeoTrace",
        "GeoTrace",
        "0.1.0",
        "f64f43b1-9ff2-47b9-badf-390b2fef25db",
        "software",
        ">=2.1,<3",
    )
    assert sorted(p.value for p in m.permissions) == [
        "api",
        "network:internet",
        "network:probe",
        "storage:own",
        "ui",
    ]
    assert sorted(c.value for c in m.capabilities) == ["api", "jobs", "storage", "web_ui"]
