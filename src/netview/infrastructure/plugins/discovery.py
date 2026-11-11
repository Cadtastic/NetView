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

LOCAL_PACKAGE = "netview_local_plugins"


@dataclass(frozen=True)
class DiscoveredPlugin:
    source: str
    cls: type[Plugin] | None
    error: str | None


def _check_class(source: str, obj: object) -> DiscoveredPlugin:
    if inspect.isclass(obj) and issubclass(obj, Plugin):
        return DiscoveredPlugin(source, obj, None)
    return DiscoveredPlugin(source, None, f"{obj!r} is not a Plugin subclass")


def _from_entry_points(group: str) -> list[DiscoveredPlugin]:
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

    A folder plugin is imported as ``netview_local_plugins.<folder>``. Its own modules (``from .service import
    ...``) are then ``netview_local_plugins.<folder>.service``, and Python imports the top package first.
    """
    if LOCAL_PACKAGE not in sys.modules:
        package = types.ModuleType(LOCAL_PACKAGE)
        package.__path__ = []
        sys.modules[LOCAL_PACKAGE] = package


def _from_folder(folder: Path) -> DiscoveredPlugin:
    source = f"folder:{folder}"
    module_name = f"{LOCAL_PACKAGE}.{folder.name}"
    try:
        _ensure_local_package()
        spec = importlib.util.spec_from_file_location(
            module_name, folder / "__init__.py", submodule_search_locations=[str(folder)]
        )
        if spec is None or spec.loader is None:
            return DiscoveredPlugin(source, None, "cannot import plugin folder")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        plugin_class = getattr(module, "plugin_class", None)
        if plugin_class is None:
            return DiscoveredPlugin(source, None, "folder defines no plugin_class")
        return _check_class(source, plugin_class)
    except Exception as exc:
        return DiscoveredPlugin(source, None, f"{type(exc).__name__}: {exc}")


def _from_dirs(extra_dirs: Sequence[Path]) -> list[DiscoveredPlugin]:
    found: list[DiscoveredPlugin] = []
    for base in extra_dirs:
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir() and (p / "__init__.py").is_file()):
            found.append(_from_folder(folder))
    return found


def discover_plugin_classes(
    group: str = "netview.plugins", extra_dirs: Sequence[Path] = ()
) -> list[DiscoveredPlugin]:
    """Entry-point plugins first, then folder plugins. Never raises."""
    return _from_entry_points(group) + _from_dirs(extra_dirs)
