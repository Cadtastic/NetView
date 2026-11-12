"""Request and response models for the core REST API."""

import ipaddress
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


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
    type_source: str
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
    os_hint: str = ""


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


class WatchStatusOut(_Out):
    ip: str
    label: str
    ports: list[int]
    state: str
    since_ms: int | None
    checked_ms: int | None
    on_subnet: bool
    l2: bool | None
    mac: str | None
    rtt_ms: float | None
    port_state: dict[str, str]
    """Keyed by the port number as a string, because JSON object keys are strings."""
    diagnosis: str
    history: list[float]

    @field_validator("port_state", mode="before")
    @classmethod
    def _string_keys(cls, value: Any) -> Any:
        return {str(k): v for k, v in value.items()} if hasattr(value, "items") else value


class WatchOut(_Out):
    ip: str
    ports: list[int]
    label: str


class WatchListItemOut(WatchOut):
    """A watch with its current status, as ``GET /watches`` returns it."""

    state: str | None = None
    since_ms: int | None = None
    checked_ms: int | None = None
    on_subnet: bool | None = None
    l2: bool | None = None
    mac: str | None = None
    rtt_ms: float | None = None
    port_state: dict[str, str] | None = None
    diagnosis: str | None = None
    history: list[float] | None = None


class TrafficOut(_Out):
    ip: str
    source: str
    down_bps: float | None
    up_bps: float | None
    down_avg_bps: float | None
    up_avg_bps: float | None
    down_total: int | None
    up_total: int | None
    seen_ms: int
    extra: dict[str, Any]


class TrafficTotalsOut(_Out):
    source: str
    clients: int
    down_bps: float
    up_bps: float
    t_ms: int


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
    watch_status: list[WatchStatusOut]
    traffic: list[TrafficOut]
    traffic_totals: list[TrafficTotalsOut]
    inspected: dict[str, int]
    """IP -> when its newest inspection finished (epoch ms)."""


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
    guid: str | None
    source_id: int | None
    display_name: str
    plugin_type: str | None
    card_key: str
    folder: str | None
    uninstallable: bool
    owns_data: bool
    name: str
    version: str
    description: str
    state: Literal["active", "disabled", "failed", "pending"]
    source: Literal["builtin", "folder"]
    error: str | None
    capabilities: list[str]
    permissions: list[str]
    enabled: bool
    restart_required: bool
    settings: dict[str, Any] | None
    """None when the caller may not change this plugin's settings."""
    settings_schema: dict[str, Any] | None
    ui_module: str | None
    configured: bool
    config_errors: dict[str, str]


class AvailableOut(_Out):
    id: str
    name: str
    version: str
    description: str
    author: str | None
    homepage: str | None
    license: str | None
    sdk_version: str
    capabilities: list[str]
    permissions: list[str]
    requires: list[str]
    path: str
    installable: bool
    reason: str | None


class CatalogOut(_Out):
    source: str
    fetched_at_ms: int | None
    error: str | None
    stale: bool
    plugins: list[AvailableOut]


class InstallIn(BaseModel):
    id: str


class UninstallIn(BaseModel):
    folder: str
    delete_data: bool = False


class UninstallOut(_Out):
    finished: bool
    error: str | None


class InstallJobOut(_Out):
    job: str
    plugin_id: str
    state: Literal["queued", "downloading", "installing", "done", "failed"]
    percent: int | None
    error: str | None


class NicknameIn(BaseModel):
    nickname: str | None = None


class WatchIn(BaseModel):
    spec: str


PORTS_SPEC = r"^(top|all|common|\d{1,5}(-\d{1,5})?(,\d{1,5}(-\d{1,5})?)*)$"


class InspectionIn(BaseModel):
    ip: Ipv4
    ports: str = Field("top", pattern=PORTS_SPEC)


class MetricsOut(BaseModel):
    now_ms: int
    series: dict[str, list[tuple[int, float | None]]]


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


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    current: str
    new: str


class SetupIn(BaseModel):
    code: str | None = None
    username: str
    password: str


class SetupStatusOut(BaseModel):
    open: bool
    code_required: bool
    password_min_length: int


class MeOut(BaseModel):
    username: str
    display_name: str
    provider: str
    must_change_password: bool
    permissions: list[str]
    is_admin: bool
    password_min_length: int
    """So a page can check a new password before sending it."""


class UserOut(_Out):
    id: int
    username: str
    display_name: str
    email: str | None
    enabled: bool
    builtin: bool
    must_change_password: bool
    role_ids: list[str]
    provider: str
    created_ms: int
    last_sign_in_ms: int | None


class UserCreateIn(BaseModel):
    username: str
    display_name: str = ""
    password: str
    role_ids: list[str] = Field(default_factory=lambda: ["default"])


class UserPatch(BaseModel):
    display_name: str | None = None
    role_ids: list[str] | None = None
    enabled: bool | None = None


class PasswordResetIn(BaseModel):
    password: str


class RoleOut(BaseModel):
    id: str
    name: str
    builtin: bool
    permissions: list[str]
    user_count: int


class RoleCreateIn(BaseModel):
    name: str
    permissions: list[str] | None = None


class RolePatch(BaseModel):
    name: str | None = None
    permissions: list[str] | None = None


class PermissionOut(_Out):
    id: str
    label: str
    description: str
    dangerous: bool
    locked: str | None


class PermissionGroupOut(_Out):
    owner: str
    title: str
    off: bool
    permissions: list[PermissionOut]


class GeneralOut(BaseModel):
    password_min_length: int
    session_idle_s: int
    session_max_s: int
    lockout_failures: int
    lockout_window_s: int
    lockout_s: int
    mode: str


class GeneralPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password_min_length: int | None = None
    session_idle_s: int | None = None
    session_max_s: int | None = None
    lockout_failures: int | None = None
    lockout_window_s: int | None = None
    lockout_s: int | None = None
