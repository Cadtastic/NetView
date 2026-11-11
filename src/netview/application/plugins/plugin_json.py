"""The ``plugin.json`` file of a folder plugin, and the index built from many of them."""

from __future__ import annotations

from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from netview.application.capabilities import Capability
from netview.application.plugins.manifest import Permission
from netview.application.plugins.validation import PLUGIN_ID_RE
from netview.domain.errors import ValidationError

PLUGIN_JSON_SCHEMA = "netview.plugin/1"
INDEX_SCHEMA = "netview.plugin-index/1"
DEFAULT_ARCHIVE_URL = "https://codeload.github.com/Cadtastic/NetView/zip/refs/heads/main"


@dataclass(frozen=True)
class PluginJson:
    id: str
    name: str
    version: str
    description: str
    sdk_version: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    author: str | None = None
    homepage: str | None = None
    license: str | None = None
    requires: tuple[str, ...] = ()


def _required_str(data: dict[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"plugin.json: {field} must be a non-empty string")
    return value


def _optional_str(data: dict[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"plugin.json: {field} must be a string")
    return value


def _str_list(data: dict[str, object], field: str, allowed: frozenset[str] | None) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValidationError(f"plugin.json: {field} must be a list")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"plugin.json: {field} must hold non-empty strings")
        if allowed is not None and item not in allowed:
            raise ValidationError(f"plugin.json: {field} has unknown value {item!r}")
        items.append(item)
    return tuple(items)


def parse_plugin_json(data: object) -> PluginJson:
    if not isinstance(data, dict):
        raise ValidationError("plugin.json: must be an object")
    if data.get("schema") != PLUGIN_JSON_SCHEMA:
        raise ValidationError(f"plugin.json: schema must be {PLUGIN_JSON_SCHEMA!r}")
    plugin_id = _required_str(data, "id")
    if not PLUGIN_ID_RE.match(plugin_id):
        raise ValidationError(f"plugin.json: id {plugin_id!r} must match {PLUGIN_ID_RE.pattern}")
    name = _required_str(data, "name")
    version = _required_str(data, "version")
    description = _required_str(data, "description")
    sdk_version = _required_str(data, "sdk_version")
    try:
        SpecifierSet(sdk_version)
    except InvalidSpecifier as exc:
        raise ValidationError(f"plugin.json: sdk_version {sdk_version!r} is invalid: {exc}") from exc
    capabilities = _str_list(data, "capabilities", frozenset(c.value for c in Capability))
    permissions = _str_list(data, "permissions", frozenset(p.value for p in Permission))
    requires = _str_list(data, "requires", None) if "requires" in data else ()
    return PluginJson(
        id=plugin_id,
        name=name,
        version=version,
        description=description,
        sdk_version=sdk_version,
        capabilities=tuple(sorted(capabilities)),
        permissions=tuple(sorted(permissions)),
        author=_optional_str(data, "author"),
        homepage=_optional_str(data, "homepage"),
        license=_optional_str(data, "license"),
        requires=requires,
    )


def plugin_json_to_dict(pj: PluginJson) -> dict[str, object]:
    out: dict[str, object] = {
        "schema": PLUGIN_JSON_SCHEMA,
        "id": pj.id,
        "name": pj.name,
        "version": pj.version,
        "description": pj.description,
    }
    if pj.author is not None:
        out["author"] = pj.author
    if pj.homepage is not None:
        out["homepage"] = pj.homepage
    if pj.license is not None:
        out["license"] = pj.license
    out["sdk_version"] = pj.sdk_version
    out["capabilities"] = sorted(pj.capabilities)
    out["permissions"] = sorted(pj.permissions)
    out["requires"] = list(pj.requires)
    return out
