"""Plugin administration port."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from netview.application.plugins.user_permissions import UserPermission


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    description: str
    state: Literal["active", "disabled", "failed", "pending"]
    error: str | None = None
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    enabled: bool = True
    restart_required: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    settings_schema: dict[str, Any] | None = None
    ui_module: str | None = None
    """URL path of the module, e.g. /plugins/lan_discovery/static/ui.js"""
    config_errors: dict[str, str] = field(default_factory=dict)
    """Settings field to message for each requirement the stored settings do not meet."""
    source: Literal["builtin", "folder"] = "builtin"
    """Where the plugin comes from: a package entry point, or a plugin folder."""
    user_permissions: list[UserPermission] = field(default_factory=list)
    """The plugin's declared user permissions, unprefixed."""

    @property
    def configured(self) -> bool:
        """True when the stored settings meet every requirement of the settings schema."""
        return not self.config_errors


class PluginAdmin(Protocol):
    def list(self) -> list[PluginInfo]: ...
    def get(self, plugin_id: str) -> PluginInfo: ...
    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo: ...
    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo: ...
