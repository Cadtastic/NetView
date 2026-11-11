"""The ``plugin.json`` file of a folder plugin, and the index built from many of them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from netview.application.capabilities import Capability
from netview.application.plugins.manifest import Permission
from netview.application.plugins.validation import PLUGIN_ID_RE, RESERVED_PLUGIN_IDS
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


@dataclass(frozen=True)
class CatalogEntry:
    plugin: PluginJson
    path: str


@dataclass(frozen=True)
class PluginIndex:
    ref: str
    archive_url: str
    plugins: tuple[CatalogEntry, ...]


def build_index(plugins: Iterable[PluginJson], ref: str, archive_url: str) -> PluginIndex:
    entries = tuple(CatalogEntry(p, f"plugins/{p.id}") for p in sorted(plugins, key=lambda p: p.id))
    return PluginIndex(ref=ref, archive_url=archive_url, plugins=entries)


def index_to_dict(index: PluginIndex) -> dict[str, object]:
    return {
        "schema": INDEX_SCHEMA,
        "ref": index.ref,
        "archive_url": index.archive_url,
        "plugins": [{**plugin_json_to_dict(e.plugin), "path": e.path} for e in index.plugins],
    }


_LOCAL_ARCHIVE_PREFIXES = ("http://127.0.0.1", "http://localhost")


def parse_index(data: object) -> PluginIndex:
    if not isinstance(data, dict):
        raise ValidationError("plugin index: must be an object")
    if data.get("schema") != INDEX_SCHEMA:
        raise ValidationError(f"plugin index: schema must be {INDEX_SCHEMA!r}")
    ref = data.get("ref")
    if not isinstance(ref, str) or not ref:
        raise ValidationError("plugin index: ref must be a non-empty string")
    archive_url = data.get("archive_url")
    if not isinstance(archive_url, str) or not archive_url:
        raise ValidationError("plugin index: archive_url must be a non-empty string")
    if not (archive_url.startswith("https://") or archive_url.startswith(_LOCAL_ARCHIVE_PREFIXES)):
        raise ValidationError("plugin index: archive_url must use https")
    raw = data.get("plugins")
    if not isinstance(raw, list):
        raise ValidationError("plugin index: plugins must be a list")
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for item in raw:
        plugin = parse_plugin_json(item)
        assert isinstance(item, dict)
        if item.get("path") != f"plugins/{plugin.id}":
            raise ValidationError(f"plugin index: path of {plugin.id!r} must be 'plugins/{plugin.id}'")
        if plugin.id in RESERVED_PLUGIN_IDS:
            raise ValidationError(f"plugin index: plugin id {plugin.id!r} is reserved")
        if plugin.id in seen:
            raise ValidationError(f"plugin index: duplicate plugin id {plugin.id!r}")
        seen.add(plugin.id)
        entries.append(CatalogEntry(plugin, f"plugins/{plugin.id}"))
    entries.sort(key=lambda e: e.plugin.id)
    return PluginIndex(ref=ref, archive_url=archive_url, plugins=tuple(entries))
