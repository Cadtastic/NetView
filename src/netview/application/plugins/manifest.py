"""Plugin manifest."""

from dataclasses import dataclass
from enum import StrEnum

from netview.application.capabilities import Capability


class Permission(StrEnum):
    DEVICES_READ = "devices:read"
    NAMES_WRITE = "names:write"
    TYPES_WRITE = "types:write"
    TRAFFIC_WRITE = "traffic:write"
    STORAGE_OWN = "storage:own"
    API = "api"
    UI = "ui"
    NETWORK_PROBE = "network:probe"


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    sdk_version: str
    capabilities: frozenset[Capability]
    permissions: frozenset[Permission]
