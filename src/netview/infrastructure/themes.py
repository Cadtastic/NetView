"""Folder-driven theme catalog: built-in themes shipped with the UI plus the user's own folder."""

from __future__ import annotations

import builtins
import re
from pathlib import Path

from netview.application.ports.themes import ThemeInfo

_STEM = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_HEADER = re.compile(r"^/\*\s*netview-theme\s(.*?)\*/", re.DOTALL)
_ATTR = re.compile(r'([a-z]+)="([^"]*)"')
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEADER_BYTES = 1024
_BUILTIN_ORDER = ("daylight", "graphite", "harbor", "contrast")


def parse_theme_header(text: str) -> tuple[str, str, list[str]]:
    """``(name, scheme, preview)`` from the leading ``netview-theme`` comment; ValueError says why not."""
    body = text.lstrip("\ufeff \t\r\n")
    match = _HEADER.match(body)
    if match is None:
        raise ValueError("the file must start with a /* netview-theme ... */ header comment")
    attrs = dict(_ATTR.findall(match.group(1)))
    name = attrs.get("name", "").strip()
    if not name:
        raise ValueError("the header has no name")
    scheme = attrs.get("scheme", "")
    if scheme not in ("light", "dark"):
        raise ValueError(f'scheme must be "light" or "dark", not {scheme!r}')
    preview = [c.strip() for c in attrs.get("preview", "").split(",")]
    if len(preview) != 3 or not all(_COLOR.match(c) for c in preview):
        raise ValueError("preview must be three #rrggbb colours separated by commas")
    return name, scheme, preview


class FolderThemeCatalog:
    """Reads both folders on every call, so a dropped-in file shows up without a restart."""

    def __init__(self, builtin_dir: Path, user_dir: Path) -> None:
        self._builtin = builtin_dir
        self._user = user_dir

    def user_dir(self) -> str:
        return str(self._user)

    def list(self) -> list[ThemeInfo]:
        builtin = self._scan(self._builtin, "built-in")
        rank = {stem: i for i, stem in enumerate(_BUILTIN_ORDER)}
        builtin.sort(key=lambda t: (rank.get(t.id, len(rank)), t.id))
        return builtin + self._scan(self._user, "user")

    # ``builtins.list``: inside this class body the method ``list`` shadows the builtin.
    @staticmethod
    def _scan(folder: Path, source: str) -> builtins.list[ThemeInfo]:
        try:
            files = sorted(p for p in folder.iterdir() if p.suffix == ".css" and p.is_file())
        except OSError:
            return []
        prefix, base = ("user-", "/themes/user/") if source == "user" else ("", "/static/themes/")
        themes: builtins.list[ThemeInfo] = []
        for path in files:
            if not _STEM.match(path.stem):
                continue
            try:
                with path.open("rb") as handle:
                    head = handle.read(_HEADER_BYTES).decode("utf-8", errors="replace")
                name, scheme, preview = parse_theme_header(head)
                error = None
            except (OSError, ValueError) as exc:
                name, scheme, preview, error = path.stem, "dark", [], str(exc)
            themes.append(
                ThemeInfo(
                    id=prefix + path.stem,
                    name=name,
                    scheme=scheme,
                    preview=preview,
                    source="user" if source == "user" else "built-in",
                    url=f"{base}{path.stem}.css",
                    error=error,
                )
            )
        return themes
