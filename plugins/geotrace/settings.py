"""GeoTrace plugin settings."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from netview.sdk import setting_group, settings_tabs

GENERAL_TAB = "General"
MAP_TAB = "Map"
LOCATION_TAB = "Location data"

GENERAL = setting_group("General", tab=GENERAL_TAB)
HOME = setting_group("Home", tab=GENERAL_TAB)
MAP = setting_group("Map", tab=MAP_TAB)
LOCATION = setting_group("Location data", tab=LOCATION_TAB)


def _with_labels(labels: dict[str, str], extra: dict[str, Any]) -> dict[str, Any]:
    return {**extra, "enum_labels": labels}


class GeoTraceSettings(BaseModel):
    model_config = ConfigDict(json_schema_extra=settings_tabs([GENERAL_TAB, MAP_TAB, LOCATION_TAB]))

    home_label: str = Field(
        default="",
        title="Home name",
        description="A name for your home location, shown on the globe.",
        json_schema_extra=HOME,
    )
    home_lat: float | None = Field(
        default=None,
        ge=-90,
        le=90,
        title="Home latitude",
        description="Latitude of your home in degrees, so the first hops start at your house.",
        json_schema_extra=HOME,
    )
    home_lon: float | None = Field(
        default=None,
        ge=-180,
        le=180,
        title="Home longitude",
        description="Longitude of your home in degrees.",
        json_schema_extra=HOME,
    )
    retention_days: int = Field(
        default=90,
        ge=7,
        le=3650,
        title="Keep traces (days)",
        description="Traces older than this are deleted every day. One-off traces are kept for 7 days.",
        json_schema_extra=GENERAL,
    )
    default_interval_min: Literal[5, 15, 30, 60] = Field(
        default=15,
        title="Default trace interval (minutes)",
        description="How often a new target is traced.",
        json_schema_extra=GENERAL,
    )
    default_family: Literal["ipv4", "ipv6"] = Field(
        default="ipv4",
        title="Default address family",
        description="Which kind of address a new target is traced over.",
        json_schema_extra=_with_labels({"ipv4": "IPv4", "ipv6": "IPv6"}, GENERAL),
    )
    tile_source: Literal["osm", "custom"] = Field(
        default="osm",
        title="Map tile source",
        description="Where the street map tiles come from.",
        json_schema_extra=_with_labels({"osm": "OpenStreetMap", "custom": "Custom tile server"}, MAP),
    )
    custom_tile_url: str = Field(
        default="",
        title="Custom tile URL",
        description="An https:// address containing {z}, {x} and {y}. Used with a custom tile server.",
        json_schema_extra={**MAP, "show_when": {"tile_source": "custom"}},
    )
    base_imagery: Literal["natural_earth", "eox_s2"] = Field(
        default="natural_earth",
        title="Globe imagery",
        description="The picture of the Earth drawn under the map tiles.",
        json_schema_extra=_with_labels(
            {
                "natural_earth": "Natural Earth (built in)",
                "eox_s2": "Sentinel-2 cloudless (EOX, non-commercial)",
            },
            MAP,
        ),
    )
    tile_cache_mb: int = Field(
        default=500,
        ge=50,
        le=20000,
        title="Tile cache size (MB)",
        description="How much disk the downloaded map tiles may use.",
        json_schema_extra=MAP,
    )
    geo_auto_update: bool = Field(
        default=True,
        title="Update location data automatically",
        description="Download the free DB-IP location database each month.",
        json_schema_extra=LOCATION,
    )

    @model_validator(mode="after")
    def _custom_tiles_need_a_template(self) -> GeoTraceSettings:
        if self.tile_source == "custom":
            url = self.custom_tile_url
            if not url.startswith("https://") or any(token not in url for token in ("{z}", "{x}", "{y}")):
                raise ValueError("custom_tile_url must start with https:// and contain {z}, {x} and {y}")
        return self
