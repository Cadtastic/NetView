"""Plugin catalog ports: where the list of installable plugins comes from and is cached."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from netview.application.plugins.plugin_json import CatalogEntry, PluginIndex


@dataclass
class CatalogSnapshot:
    index: PluginIndex | None
    source: str
    fetched_at_ms: int | None
    error: str | None


class CatalogFetcher(Protocol):
    source: str

    def fetch(self) -> PluginIndex:
        """The current index. Raises ``CatalogUnavailableError`` with a message fit for the user."""
        ...


class CatalogStore(Protocol):
    def load(self) -> CatalogSnapshot | None: ...
    def save(self, snapshot: CatalogSnapshot) -> None: ...


Progress = Callable[[str, int | None], None]
"""Called with a phase (``"downloading"`` or ``"installing"``) and a percent, or ``None`` when unknown."""


class PluginInstaller(Protocol):
    def install(self, entry: CatalogEntry, archive_url: str, progress: Progress) -> None:
        """Put the plugin's folder into the plugin folder. Raises ``InstallError`` or ``ConflictError``."""
        ...
