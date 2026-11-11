"""Plugin catalog ports: where the list of installable plugins comes from and is cached."""

from dataclasses import dataclass
from typing import Protocol

from netview.application.plugins.plugin_json import PluginIndex


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
