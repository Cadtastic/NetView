"""GS105E plugin settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from netview.sdk import setting_group, settings_requirements, settings_tabs

# settings form tabs, in this order, and the sections on them (each section starts at its first field)
GENERAL_TAB = "General"
CONNECTION_TAB = "Connection"
CONNECTION = setting_group("Switch", tab=CONNECTION_TAB)
POLLING = setting_group("Polling", tab=GENERAL_TAB)
RETENTION = setting_group("Traffic history", tab=GENERAL_TAB)
ALERTS = setting_group("Alerts", tab=GENERAL_TAB)

# What configured() needs, stated in the settings schema so the host and the settings form agree on it.
REQUIREMENTS = settings_requirements(required=["host", "password"])


class Gs105eSettings(BaseModel):
    model_config = ConfigDict(
        json_schema_extra=settings_tabs([GENERAL_TAB, CONNECTION_TAB], then=REQUIREMENTS)
    )

    host: str = Field(
        "192.168.1.3", description="IP address or host name of the switch", json_schema_extra=CONNECTION
    )
    port: int = Field(
        80, ge=1, le=65535, description="TCP port of the switch's web interface", json_schema_extra=CONNECTION
    )
    password: SecretStr | None = Field(
        None,
        title="Password",
        description=(
            "The switch's web password. Stored in netview's local database. Disabling this plugin takes "
            "effect after a restart; use Pause on the Switch page to free the switch's login at once."
        ),
        json_schema_extra=CONNECTION,
    )
    counters_interval_s: int = Field(
        15,
        title="Port traffic (s)",
        ge=5,
        le=300,
        description="Seconds between port traffic counter polls",
        json_schema_extra=POLLING,
    )
    status_interval_s: int = Field(
        30,
        title="Port status (s)",
        ge=10,
        le=600,
        description="Seconds between port status polls",
        json_schema_extra=POLLING,
    )
    config_interval_s: int = Field(
        300,
        title="Configuration (s)",
        ge=60,
        le=3600,
        description="Seconds between VLAN, QoS, IGMP, mirroring and management polls",
        json_schema_extra=POLLING,
    )
    page_gap_ms: int = Field(
        200,
        title="Gap between requests (ms)",
        ge=0,
        le=2000,
        description="Milliseconds to wait between two requests to the switch, which is slow and fragile",
        json_schema_extra=POLLING,
    )
    pause_minutes: int = Field(
        15,
        title="Pause length (min)",
        ge=1,
        le=240,
        description="Minutes to stay logged out after Pause, or after another login keeps ending the session",
        json_schema_extra=POLLING,
    )
    raw_retention_h: int = Field(
        24,
        title="Keep raw samples (h)",
        ge=1,
        le=168,
        description="Hours to keep every traffic sample",
        json_schema_extra=RETENTION,
    )
    rollup_retention_d: int = Field(
        30,
        title="Keep 5-minute averages (days)",
        ge=1,
        le=365,
        description="Days to keep the 5-minute traffic averages",
        json_schema_extra=RETENTION,
    )
    crc_alert_threshold: int = Field(
        10,
        title="CRC error alert",
        ge=1,
        le=1_000_000,
        description="Raise an event when a port counts more than this many new CRC errors between two polls",
        json_schema_extra=ALERTS,
    )

    def password_text(self) -> str | None:
        """The password as plain text, or None when it is unset or empty."""
        text = self.password.get_secret_value() if self.password is not None else ""
        return text or None

    def configured(self) -> bool:
        return bool(self.host) and self.password_text() is not None
