"""Pure checks a plugin must pass before it is loaded."""

from __future__ import annotations

import re
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from netview.application.capabilities import Capability
from netview.application.plugins.base import Plugin
from netview.application.plugins.manifest import PluginManifest

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Ids that would collide with core route segments under /api/v1/plugins/.
RESERVED_PLUGIN_IDS = frozenset({"catalog", "install"})


def validate_manifest(m: PluginManifest, sdk_version: str, seen_ids: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(m.id, str) or not PLUGIN_ID_RE.fullmatch(m.id):
        errors.append(f"plugin id {m.id!r} must match {PLUGIN_ID_RE.pattern}")
    try:
        if Version(sdk_version) not in SpecifierSet(m.sdk_version):
            errors.append(f"sdk_version {m.sdk_version!r} is not satisfied by SDK {sdk_version}")
    except (InvalidSpecifier, InvalidVersion) as exc:
        errors.append(f"invalid sdk_version {m.sdk_version!r}: {exc}")
    if isinstance(m.id, str) and m.id in RESERVED_PLUGIN_IDS:
        errors.append(f"plugin id {m.id!r} is reserved")
    if m.id in seen_ids:
        errors.append(f"duplicate plugin id {m.id!r}")
    unknown = sorted(str(c) for c in m.capabilities if not isinstance(c, Capability))
    if unknown:
        errors.append(f"unknown capabilities: {', '.join(unknown)}")
    return errors


def validate_storage(plugin_id: str, metadata: Any) -> list[str]:
    prefix = f"{plugin_id}_"
    return [
        f"table {name!r} must start with the prefix {prefix!r}"
        for name in sorted(metadata.tables)
        if not name.startswith(prefix)
    ]


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
