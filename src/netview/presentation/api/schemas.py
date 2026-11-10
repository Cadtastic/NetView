"""Request and response models for the core REST API."""

import ipaddress
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict


def _check_ipv4(value: str) -> str:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError(f"{value!r} is not an IPv4 address") from None
    return value


Ipv4 = Annotated[str, AfterValidator(_check_ipv4)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DeviceOut(_Out):
    key: str
    ip: str
    mac: str | None
    vendor: str
    nickname: str | None
    device_name: str
    name_source: str
    type: str
    hints: list[str]
    status: str
    rtt_ms: float | None
    ttl: int | None
    first_seen_ms: int
    last_seen_ms: int
    is_new: bool
    is_self: bool
    watched: bool
    display_name: str


class HostInfoOut(_Out):
    hostname: str
    ip: str
    gateway: str | None
    subnet: str
    platform: str


class EventOut(_Out):
    kind: str
    text: str
    t_ms: int
    ip: str | None = None
    key: str | None = None


class WatchOut(_Out):
    ip: str
    ports: list[int]
    label: str


class JobStatusOut(_Out):
    owner: str
    name: str
    last_run_ms: int | None
    last_ok: bool | None
    last_error: str | None
    consecutive_failures: int
    next_run_ms: int | None
    running: bool
    last_finished_ms: int | None = None


class NetworkStateOut(_Out):
    host: HostInfoOut
    devices: list[DeviceOut]
    events: list[EventOut]
    watches: list[WatchOut]
    capabilities: list[str]
    jobs: list[JobStatusOut]


class SweepSummaryOut(_Out):
    seen: int
    replied: int
    quiet: int
    went_offline: int
    new: int
    duration_ms: int


class ReportSectionOut(_Out):
    plugin_id: str
    id: str
    title: str
    data: dict[str, Any]
    error: str | None = None


class InspectionReportOut(_Out):
    ip: str
    ports_spec: str
    started_ms: int
    finished_ms: int
    sections: list[ReportSectionOut]


class PluginOut(_Out):
    id: str
    name: str
    version: str
    description: str
    state: Literal["active", "disabled", "failed"]
    error: str | None
    capabilities: list[str]
    permissions: list[str]
    enabled: bool
    restart_required: bool
    settings: dict[str, Any]
    settings_schema: dict[str, Any] | None
    ui_module: str | None


class NicknameIn(BaseModel):
    nickname: str | None = None


class WatchIn(BaseModel):
    spec: str


class InspectionIn(BaseModel):
    ip: Ipv4
    ports: str = "top"


class PluginPatch(BaseModel):
    enabled: bool | None = None
    settings: dict[str, Any] | None = None


class ThemeOut(_Out):
    id: str
    name: str
    scheme: str
    preview: list[str]
    source: Literal["built-in", "user"]
    url: str
    error: str | None


class ThemeListOut(BaseModel):
    themes: list[ThemeOut]
    user_dir: str
