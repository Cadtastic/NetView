"""The ``plugin.json`` file of a folder plugin, and the index built from many of them."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from netview.application.capabilities import Capability
from netview.application.plugins.manifest import Permission
from netview.application.plugins.plugin_type import PluginType
from netview.application.plugins.validation import GUID_RE, PATH_SEGMENT_RE
from netview.domain.errors import ValidationError

PLUGIN_JSON_SCHEMA = "netview.plugin/2"
INDEX_SCHEMA = "netview.plugin-index/2"
_PATH_RE = re.compile(r"^plugins/" + PATH_SEGMENT_RE.pattern.lstrip("^"))
DEFAULT_ARCHIVE_URL = "https://codeload.github.com/Cadtastic/NetView/zip/refs/heads/main"


@dataclass(frozen=True)
class PluginJson:
    name: str
    version: str
    description: str
    guid: str
    display_name: str
    plugin_type: str
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


_FIELDS = frozenset(
    {
        "schema",
        "name",
        "version",
        "description",
        "guid",
        "display_name",
        "plugin_type",
        "author",
        "homepage",
        "license",
        "sdk_version",
        "capabilities",
        "permissions",
        "requires",
    }
)


def parse_plugin_json(data: object) -> PluginJson:
    if not isinstance(data, dict):
        raise ValidationError("plugin.json: must be an object")
    if data.get("schema") != PLUGIN_JSON_SCHEMA:
        raise ValidationError(f"plugin.json: schema must be {PLUGIN_JSON_SCHEMA!r}")
    for key in data:
        if key not in _FIELDS:
            raise ValidationError(f"plugin.json: unknown field {key}")
    name = _required_str(data, "name")
    version = _required_str(data, "version")
    description = _required_str(data, "description")
    guid = _required_str(data, "guid")
    if not GUID_RE.fullmatch(guid):
        raise ValidationError(f"plugin.json: guid {guid!r} must be a lower-case UUID")
    display_name = _required_str(data, "display_name")
    plugin_type = _required_str(data, "plugin_type")
    if plugin_type not in {t.value for t in PluginType}:
        raise ValidationError(f"plugin.json: plugin_type has unknown value {plugin_type!r}")
    sdk_version = _required_str(data, "sdk_version")
    try:
        SpecifierSet(sdk_version)
    except InvalidSpecifier as exc:
        raise ValidationError(f"plugin.json: sdk_version {sdk_version!r} is invalid: {exc}") from exc
    capabilities = _str_list(data, "capabilities", frozenset(c.value for c in Capability))
    permissions = _str_list(data, "permissions", frozenset(p.value for p in Permission))
    requires = _str_list(data, "requires", None) if "requires" in data else ()
    return PluginJson(
        name=name,
        version=version,
        description=description,
        guid=guid,
        display_name=display_name,
        plugin_type=plugin_type,
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
        "name": pj.name,
        "version": pj.version,
        "description": pj.description,
        "guid": pj.guid,
        "display_name": pj.display_name,
        "plugin_type": pj.plugin_type,
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


def build_index(entries: Iterable[CatalogEntry], ref: str, archive_url: str) -> PluginIndex:
    """An index of ``entries``, ordered by path."""
    return PluginIndex(ref=ref, archive_url=archive_url, plugins=tuple(sorted(entries, key=lambda e: e.path)))


def index_to_dict(index: PluginIndex) -> dict[str, object]:
    return {
        "schema": INDEX_SCHEMA,
        "ref": index.ref,
        "archive_url": index.archive_url,
        "plugins": [{**plugin_json_to_dict(e.plugin), "path": e.path} for e in index.plugins],
    }


_LOCAL_ARCHIVE_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _archive_url_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme == "https":
        return bool(host)
    return parts.scheme == "http" and host in _LOCAL_ARCHIVE_HOSTS


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
    if not _archive_url_allowed(archive_url):
        raise ValidationError("plugin index: archive_url must use https")
    raw = data.get("plugins")
    if not isinstance(raw, list):
        raise ValidationError("plugin index: plugins must be a list")
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("plugin.json: must be an object")
        path = item.get("path")
        if not isinstance(path, str) or not _PATH_RE.fullmatch(path):
            raise ValidationError(f"plugin index: path {path!r} must match {_PATH_RE.pattern}")
        plugin = parse_plugin_json({k: v for k, v in item.items() if k != "path"})
        if plugin.guid in seen:
            raise ValidationError(f"plugin index: duplicate guid {plugin.guid!r}")
        seen.add(plugin.guid)
        entries.append(CatalogEntry(plugin, path))
    entries.sort(key=lambda e: e.path)
    return PluginIndex(ref=ref, archive_url=archive_url, plugins=tuple(entries))


def installable(pj: PluginJson, sdk_version: str, has_package: Callable[[str], bool]) -> str | None:
    """Why this netview cannot run the plugin, or ``None`` when it can."""
    if Version(sdk_version) not in SpecifierSet(pj.sdk_version):
        return "Needs a newer netview"
    for package in pj.requires:
        if not has_package(package):
            return f"Needs {package}, which this netview does not have"
    return None
