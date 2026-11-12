"""Find plugin classes from entry points and from local plugin folders."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import inspect
import sys
import types
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from netview.application.plugins.base import Plugin
from netview.application.plugins.plugin_json import PluginJson
from netview.infrastructure.plugins.folders import read_plugin_json

LOCAL_PACKAGE = "netview_local_plugins"


@dataclass(frozen=True)
class DiscoveredPlugin:
    source: str
    cls: type[Plugin] | None
    error: str | None
    folder: Path | None = None


def _check_class(source: str, obj: object, folder: Path | None = None) -> DiscoveredPlugin:
    if inspect.isclass(obj) and issubclass(obj, Plugin):
        return DiscoveredPlugin(source, obj, None, folder)
    return DiscoveredPlugin(source, None, f"{obj!r} is not a Plugin subclass", folder)


def find_entry_points(group: str = "netview.plugins") -> list[DiscoveredPlugin]:
    found: list[DiscoveredPlugin] = []
    for ep in importlib.metadata.entry_points(group=group):
        source = f"entry_point:{ep.name}"
        try:
            found.append(_check_class(source, ep.load()))
        except Exception as exc:  # a broken plugin must never stop discovery
            found.append(DiscoveredPlugin(source, None, f"{type(exc).__name__}: {exc}"))
    return found


def _ensure_local_package() -> None:
    """Make the parent package of every folder plugin.

    A folder plugin is imported as ``netview_local_plugins.p<source_id>``. Its own modules (``from .service
    import ...``) are then ``netview_local_plugins.p<source_id>.service``, and Python imports the top package
    first.
    """
    if LOCAL_PACKAGE not in sys.modules:
        package = types.ModuleType(LOCAL_PACKAGE)
        package.__path__ = []
        sys.modules[LOCAL_PACKAGE] = package


@dataclass(frozen=True)
class FolderCandidate:
    """A plugin folder found on disk, not imported. ``error`` is set when its plugin.json cannot be used."""

    folder: Path
    tier: int
    plugin_json: PluginJson | None
    error: str | None


def import_folder(folder: Path, source_id: int) -> DiscoveredPlugin:
    """Import a plugin folder as ``netview_local_plugins.p<source_id>``; the folder's name is irrelevant."""
    source = f"folder:{folder.resolve()}"
    module_name = f"{LOCAL_PACKAGE}.p{source_id}"
    try:
        _ensure_local_package()
        spec = importlib.util.spec_from_file_location(
            module_name, folder / "__init__.py", submodule_search_locations=[str(folder)]
        )
        if spec is None or spec.loader is None:
            return DiscoveredPlugin(source, None, "cannot import plugin folder", folder)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        plugin_class = getattr(module, "plugin_class", None)
        if plugin_class is None:
            return DiscoveredPlugin(source, None, "folder defines no plugin_class", folder)
        return _check_class(source, plugin_class, folder)
    except Exception as exc:
        return DiscoveredPlugin(source, None, f"{type(exc).__name__}: {exc}", folder)


def find_folders(bases: Sequence[tuple[Path, int]]) -> list[FolderCandidate]:
    """Plugin folders under each ``(base, tier)``, read from their plugin.json. Imports nothing."""
    found: list[FolderCandidate] = []
    for base, tier in bases:
        if not base.is_dir():
            continue
        for folder in sorted(
            p
            for p in base.iterdir()
            if p.is_dir() and not p.name.startswith(".") and (p / "__init__.py").is_file()
        ):
            pj = read_plugin_json(folder)
            error = None if pj is not None else "plugin.json is missing or invalid"
            found.append(FolderCandidate(folder, tier, pj, error))
    return found
