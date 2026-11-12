"""Plugin manifest."""

from dataclasses import dataclass
from enum import StrEnum

from netview.application.capabilities import Capability
from netview.application.plugins.plugin_type import PluginType

SDK_VERSION = "1.5"


class Permission(StrEnum):
    DEVICES_READ = "devices:read"
    NAMES_WRITE = "names:write"
    TYPES_WRITE = "types:write"
    TRAFFIC_WRITE = "traffic:write"
    STORAGE_OWN = "storage:own"
    API = "api"
    UI = "ui"
    NETWORK_PROBE = "network:probe"
    NETWORK_CONTROL = "network:control"


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    guid: str
    display_name: str
    plugin_type: PluginType
    sdk_version: str
    capabilities: frozenset[Capability]
    permissions: frozenset[Permission]
