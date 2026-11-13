"""Pure checks a plugin must pass before it is loaded."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from netview.application.capabilities import Capability
from netview.application.plugins.base import Plugin
from netview.application.plugins.manifest import PluginManifest
from netview.application.plugins.plugin_type import PluginType

if TYPE_CHECKING:
    from netview.application.plugins.plugin_json import PluginJson

# One folder name: the last segment of an index entry path, and the install folder.
PATH_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def validate_manifest(m: PluginManifest, sdk_version: str) -> list[str]:
    errors: list[str] = []
    try:
        if Version(sdk_version) not in SpecifierSet(m.sdk_version):
            errors.append(f"sdk_version {m.sdk_version!r} is not satisfied by SDK {sdk_version}")
    except (InvalidSpecifier, InvalidVersion) as exc:
        errors.append(f"invalid sdk_version {m.sdk_version!r}: {exc}")
    if not isinstance(m.guid, str) or not GUID_RE.fullmatch(m.guid):
        errors.append(f"guid {m.guid!r} must be a lower-case UUID")
    if not isinstance(m.display_name, str) or not m.display_name.strip():
        errors.append("display_name must be a non-empty string")
    if not isinstance(m.plugin_type, PluginType):
        errors.append(f"plugin_type {m.plugin_type!r} must be a PluginType")
    unknown = sorted(str(c) for c in m.capabilities if not isinstance(c, Capability))
    if unknown:
        errors.append(f"unknown capabilities: {', '.join(unknown)}")
    return errors


def validate_providers(plugin: Plugin) -> list[str]:
    declared = plugin.manifest.capabilities
    errors = [
        f"provider {getattr(cap, 'value', cap)} is undeclared in manifest capabilities"
        for cap in plugin.providers()
        if cap not in declared
    ]
    if plugin.router() is not None and Capability.API not in declared:
        errors.append("router() requires the api capability, which is undeclared")
    if plugin.ui() is not None and Capability.WEB_UI not in declared:
        errors.append("ui() requires the web_ui capability, which is undeclared")
    if plugin.storage() is not None and Capability.STORAGE not in declared:
        errors.append("storage() requires the storage capability, which is undeclared")
    if plugin.jobs() and Capability.JOBS not in declared:
        errors.append("jobs() requires the jobs capability, which is undeclared")
    return errors


def manifest_mismatch(m: PluginManifest, pj: PluginJson) -> list[str]:
    """Names of the fields ``plugin.json`` and the manifest disagree on."""
    pairs = {
        "name": (m.name, pj.name),
        "version": (m.version, pj.version),
        "description": (m.description, pj.description),
        "guid": (m.guid, pj.guid),
        "display_name": (m.display_name, pj.display_name),
        "plugin_type": (str(m.plugin_type), pj.plugin_type),
        "sdk_version": (m.sdk_version, pj.sdk_version),
        "capabilities": (sorted(str(c) for c in m.capabilities), sorted(pj.capabilities)),
        "permissions": (sorted(str(p) for p in m.permissions), sorted(pj.permissions)),
    }
    return [name for name, (a, b) in pairs.items() if a != b]
