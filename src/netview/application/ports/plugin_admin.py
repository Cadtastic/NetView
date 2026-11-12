"""Plugin administration port."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from netview.application.plugins.user_permissions import UserPermission


@dataclass
class PluginInfo:
    id: str
    """The runtime key: ``str(source_id)`` of a registered plugin, else its ``card_key``. Used in URLs."""
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
    """URL path of the module, e.g. /plugins/3/static/ui.js"""
    config_errors: dict[str, str] = field(default_factory=dict)
    """Settings field to message for each requirement the stored settings do not meet."""
    source: Literal["builtin", "folder"] = "builtin"
    """Where the plugin comes from: a package entry point, or a plugin folder."""
    user_permissions: list[UserPermission] = field(default_factory=list)
    """The plugin's declared user permissions, unprefixed."""
    guid: str | None = None
    """The permanent identity; keys saved state and permissions. None for a card with no valid one."""
    source_id: int | None = None
    """The number NetView assigned to the guid; None for a card that was never registered."""
    display_name: str = ""
    plugin_type: str | None = None
    card_key: str = ""
    """``entry_point:<name>`` or ``folder:<resolved path>``: which found plugin this card is."""
    folder: str | None = None
    """The folder name when the plugin lives directly in ``<data dir>/plugins``, else None."""
    owns_data: bool = True
    """True for the card that won its guid (the only one that may own the plugin's saved data)."""

    @property
    def uninstallable(self) -> bool:
        return self.folder is not None

    @property
    def configured(self) -> bool:
        """True when the stored settings meet every requirement of the settings schema."""
        return not self.config_errors


@dataclass
class UninstallResult:
    finished: bool
    """False when the folder could not be removed now; it is removed at the next start."""
    error: str | None


class PluginAdmin(Protocol):
    def list(self) -> list[PluginInfo]: ...
    def get(self, plugin_id: str) -> PluginInfo: ...
    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo: ...
    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo: ...
    def uninstall(self, folder: str, delete_data: bool) -> UninstallResult: ...
