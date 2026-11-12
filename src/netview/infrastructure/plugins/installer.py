"""Install a plugin folder from a repository archive into the plugin folder."""

from __future__ import annotations

import http.client
import re
import shutil
import stat
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from netview import __version__
from netview.application.plugins.plugin_json import CatalogEntry
from netview.application.ports.plugin_catalog import Progress
from netview.domain.errors import ConflictError, InstallError
from netview.infrastructure.plugins.folders import STAGING, read_plugin_json

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SKIPPED_DIRS = frozenset({"tests", "__pycache__"})
_CHUNK = 64 * 1024


def _check_name(name: str) -> None:
    """Refuse an archive entry name that could land outside the destination on any OS."""
    if name.startswith(("/", "\\")) or "\\" in name:
        raise InstallError(f"the archive holds an unsafe path: {name!r}")
    for part in name.split("/"):
        if part == ".." or _DRIVE_RE.match(part):
            raise InstallError(f"the archive holds an unsafe path: {name!r}")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def extract_plugin(archive: Path, plugin_path: str, dest: Path, max_unpacked: int = 20_000_000) -> None:
    """Copy ``<top>/<plugin_path>/...`` of the archive into ``dest``, skipping tests and bytecode caches."""
    root = dest.resolve()
    total = 0
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise InstallError("the downloaded archive is not a valid zip file") from exc
    with zf:
        infos = zf.infolist()
        for info in infos:
            _check_name(info.filename)
        tops = {info.filename.split("/", 1)[0] for info in infos if info.filename}
        if len(tops) != 1:
            raise InstallError("the archive does not hold exactly one top folder")
        prefix = f"{tops.pop()}/{plugin_path.strip('/')}/"
        copied = 0
        for info in infos:
            if not info.filename.startswith(prefix):
                continue
            relative = info.filename[len(prefix) :]
            if _is_symlink(info):
                raise InstallError(f"the archive holds a link: {info.filename!r}")
            if not relative or info.is_dir():
                continue
            parts = relative.split("/")
            if any(part in _SKIPPED_DIRS for part in parts[:-1]):
                continue
            total += info.file_size
            if total > max_unpacked:
                raise InstallError("the plugin is larger than the allowed size")
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise InstallError(f"the archive holds an unsafe path: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            copied += 1
    if copied == 0:
        raise InstallError(f"the archive has no {plugin_path} folder")


class ZipPluginInstaller:
    def __init__(
        self,
        target: Path,
        opener: Callable[..., Any] = urllib.request.urlopen,
        max_download: int = 50_000_000,
        read_timeout_s: float = 30.0,
    ) -> None:
        self._target = target
        self._opener = opener
        self._max_download = max_download
        self._read_timeout_s = read_timeout_s

    def _download(self, url: str, to: Path, progress: Progress) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": f"netview/{__version__}"})
        try:
            with self._opener(request, timeout=self._read_timeout_s) as response:
                length_text = response.headers.get("Content-Length")
                length = int(length_text) if length_text and length_text.isdigit() else None
                if length is not None and length > self._max_download:
                    raise InstallError("the download is larger than the allowed size")
                done = 0
                progress("downloading", 0 if length else None)
                with open(to, "wb") as out:
                    while chunk := response.read(_CHUNK):
                        done += len(chunk)
                        if done > self._max_download:
                            raise InstallError("the download is larger than the allowed size")
                        out.write(chunk)
                        progress("downloading", min(100, done * 100 // length) if length else None)
        except InstallError:
            raise
        except urllib.error.HTTPError as exc:
            raise InstallError(f"Couldn't download the plugin ({exc.code})") from exc
        except (OSError, http.client.HTTPException) as exc:  # network errors and timeouts
            raise InstallError("Couldn't reach GitHub") from exc

    def _known_guids(self) -> set[str]:
        """Every guid with a valid ``plugin.json`` in a folder of the plugin folder."""
        guids: set[str] = set()
        if self._target.is_dir():
            for folder in self._target.iterdir():
                if folder.name.startswith(".") or not folder.is_dir():
                    continue
                found = read_plugin_json(folder)
                if found is not None:
                    guids.add(found.guid)
        return guids

    def _free_name(self, base: str) -> str:
        """``base``, or ``base-2``, ``base-3``... when a folder of that name already exists."""
        name, n = base, 1
        while (self._target / name).exists():
            n += 1
            name = f"{base}-{n}"
        return name

    def install(self, entry: CatalogEntry, archive_url: str, progress: Progress) -> None:
        guid = entry.plugin.guid
        if guid in self._known_guids():
            raise ConflictError(f"{entry.plugin.name} is already installed")
        base = entry.path.rstrip("/").rsplit("/", 1)[-1]
        staging = self._target / STAGING
        archive = staging / f"{base}.zip"
        staged = staging / base
        try:
            staging.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(staged, ignore_errors=True)
            self._download(archive_url, archive, progress)
            progress("installing", None)
            extract_plugin(archive, entry.path, staged)
            if not (staged / "__init__.py").is_file():
                raise InstallError("the plugin folder has no __init__.py")
            found = read_plugin_json(staged)
            if found is None or found.guid != guid:
                raise InstallError("the plugin folder has no valid plugin.json for this plugin")
            for _ in range(3):  # a folder may appear between the name check and the move
                final = self._target / self._free_name(base)
                try:
                    staged.replace(final)
                except OSError as exc:
                    if final.exists():
                        continue
                    raise InstallError("the plugin could not be moved into place") from exc
                return
            raise InstallError("the plugin could not be moved into place")
        finally:
            archive.unlink(missing_ok=True)
            shutil.rmtree(staged, ignore_errors=True)
