"""Plugin folders on disk: their ``plugin.json``, folders not loaded yet, and the install staging area."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Sequence
from pathlib import Path

from netview.application.plugins.plugin_json import PluginJson, parse_plugin_json
from netview.domain.errors import ValidationError

log = logging.getLogger(__name__)

STAGING = ".staging"


def read_plugin_json(folder: Path) -> PluginJson | None:
    """The folder's ``plugin.json``; ``None`` when it is missing or invalid (invalid is logged)."""
    path = folder / "plugin.json"
    if not path.is_file():
        return None
    try:
        return parse_plugin_json(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("ignoring %s: %s", path, exc)
        return None


def folder_plugins(bases: Sequence[Path]) -> list[tuple[Path, PluginJson]]:
    """Plugin folders under ``bases`` that carry a valid ``plugin.json``, sorted by plugin id."""
    found: list[tuple[Path, PluginJson]] = []
    for base in bases:
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            if folder.name.startswith(".") or not folder.is_dir() or not (folder / "__init__.py").is_file():
                continue
            pj = read_plugin_json(folder)
            if pj is not None:
                found.append((folder, pj))
    return sorted(found, key=lambda item: item[1].id)


def clear_staging(base: Path) -> None:
    """Remove leftovers of an install that was interrupted."""
    shutil.rmtree(base / STAGING, ignore_errors=True)
