"""Plugin folders on disk: their ``plugin.json``, folders not loaded yet, and the install staging area."""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from netview.application.plugins.plugin_json import PluginJson, parse_plugin_json
from netview.domain.errors import ValidationError

log = logging.getLogger(__name__)

STAGING = ".staging"
TRASH = ".trash"


def read_plugin_json_reason(folder: Path) -> tuple[PluginJson | None, str | None]:
    """The folder's ``plugin.json`` and, when it is unusable, why; a missing file has no reason."""
    path = folder / "plugin.json"
    if not path.is_file():
        return None, None
    try:
        return parse_plugin_json(json.loads(path.read_text(encoding="utf-8-sig"))), None
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("ignoring %s: %s", path, exc)
        reason = str(exc) or type(exc).__name__
        return None, reason.removeprefix("plugin.json: ")


def read_plugin_json(folder: Path) -> PluginJson | None:
    """The folder's ``plugin.json``; ``None`` when it is missing or invalid (invalid is logged)."""
    return read_plugin_json_reason(folder)[0]


def folder_plugins(bases: Sequence[Path]) -> list[tuple[Path, PluginJson]]:
    """Plugin folders under ``bases`` that carry a valid ``plugin.json``, sorted by folder name."""
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
    return sorted(found, key=lambda item: (item[0].name, str(item[0])))


def clear_staging(base: Path) -> None:
    """Remove leftovers of an install that was interrupted."""
    shutil.rmtree(base / STAGING, ignore_errors=True)


def direct_child(base: Path, name: str) -> Path | None:
    """``base / name`` resolved, when it is a direct, non-dot child of ``base``; else ``None``.

    A link or junction that points elsewhere resolves elsewhere, so it is refused.
    """
    if not name or name.startswith("."):
        return None
    resolved = (base / name).resolve()
    if resolved.parent != base.resolve() or resolved.name.startswith("."):
        return None
    return resolved


def move_to_trash(base: Path, folder: Path) -> Path:
    """Rename ``folder`` to ``<base>/.trash/<name>-<epoch ms>``; raises OSError when it cannot."""
    trash = base / TRASH
    trash.mkdir(exist_ok=True)
    target = trash / f"{folder.name}-{time.time_ns() // 1_000_000}"
    folder.rename(target)
    return target


def clear_trash(base: Path) -> None:
    """Remove what earlier uninstalls could not delete."""
    shutil.rmtree(base / TRASH, ignore_errors=True)


def finish_pending_uninstalls(
    base: Path, pending: Iterable[str], clear: Callable[[str], None]
) -> dict[Path, str]:
    """Remove folders whose uninstall could not rename them, before any plugin is loaded.

    An entry is a folder name or the resolved path recorded at the time. One that is not (any more) a
    direct child of ``base`` is dropped without touching anything. One that still cannot be moved stays
    pending for the next start; those are returned (resolved folder to the reason), and must not be loaded.
    """
    unfinished: dict[Path, str] = {}
    for entry in list(pending):
        path = Path(entry)
        folder = direct_child(base, path.name) if path.parent in (Path("."), base, base.resolve()) else None
        if folder is not None and folder.exists():
            try:
                shutil.rmtree(move_to_trash(base, folder), ignore_errors=True)
            except OSError as exc:
                log.warning("cannot remove %s yet: %s", folder, exc)
                unfinished[folder] = str(exc) or type(exc).__name__
                continue
        clear(entry)
    return unfinished
