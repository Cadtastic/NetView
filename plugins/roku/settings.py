"""Roku plugin settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from netview.sdk import setting_group

SCANNING = setting_group("Scanning")
SCANNING_EVERY = setting_group("Scanning", show_when={"auto_scan": "startup_and_every"})
LIVE_STATUS = setting_group("Live status")


class RokuSettings(BaseModel):
    auto_scan: Literal["never", "startup", "startup_and_every"] = Field(
        default="startup_and_every",
        title="Look for Roku TVs automatically",
        description="Never, once when NetView starts, or when it starts and then again on a schedule.",
        json_schema_extra=SCANNING,
    )
    scan_every_h: int = Field(
        default=6,
        ge=1,
        le=168,
        title="Scan every (hours)",
        description="How many hours pass between automatic scans.",
        json_schema_extra=SCANNING_EVERY,
    )
    scan_timeout_s: float = Field(
        default=2,
        ge=0.5,
        le=10,
        title="Scan wait (seconds)",
        description="How long a scan waits for each address to answer. Raise it on a slow network.",
        json_schema_extra=SCANNING,
    )
    status_interval_s: int = Field(
        default=10,
        ge=5,
        le=300,
        title="Status refresh (seconds)",
        description="How often NetView asks each saved TV whether it is on and what it is playing.",
        json_schema_extra=LIVE_STATUS,
    )
    request_timeout_s: float = Field(
        default=2,
        ge=0.5,
        le=10,
        title="TV answer wait (seconds)",
        description="How long to wait for a TV to answer a status request or a command.",
        json_schema_extra=LIVE_STATUS,
    )
