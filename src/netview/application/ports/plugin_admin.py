"""Plugin administration port."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    description: str
    state: Literal["active", "disabled", "failed"]
    error: str | None = None
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    enabled: bool = True
    restart_required: bool = False
    settings: dict[str, Any] = field(default_factory=dict)
    settings_schema: dict[str, Any] | None = None
    ui_module: str | None = None
    """URL path of the module, e.g. /plugins/lan_discovery/static/ui.js"""


class PluginAdmin(Protocol):
    def list(self) -> list[PluginInfo]: ...
    def get(self, plugin_id: str) -> PluginInfo: ...
    def update_settings(self, plugin_id: str, values: dict[str, Any]) -> PluginInfo: ...
    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo: ...
