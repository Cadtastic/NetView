"""The catalog of plugins that can be installed, cached and refreshed on demand."""

from collections.abc import Callable
from dataclasses import dataclass

from netview.application.plugins.plugin_json import CatalogEntry, PluginIndex, installable
from netview.application.ports.clock import Clock
from netview.application.ports.plugin_admin import PluginAdmin
from netview.application.ports.plugin_catalog import CatalogFetcher, CatalogSnapshot, CatalogStore
from netview.domain.errors import CatalogUnavailableError, NotFoundError

BUNDLED_SOURCE = "bundled"


@dataclass(frozen=True)
class AvailablePlugin:
    entry: CatalogEntry
    reason: str | None

    @property
    def installable(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class CatalogView:
    source: str
    fetched_at_ms: int | None
    error: str | None
    stale: bool
    plugins: list[AvailablePlugin]


class PluginCatalogService:
    def __init__(
        self,
        store: CatalogStore,
        fetcher: CatalogFetcher,
        bundled: Callable[[], PluginIndex],
        admin: PluginAdmin,
        clock: Clock,
        sdk_version: str,
        has_package: Callable[[str], bool],
        max_age_ms: int = 3_600_000,
    ) -> None:
        self._store = store
        self._fetcher = fetcher
        self._bundled = bundled
        self._admin = admin
        self._clock = clock
        self._sdk_version = sdk_version
        self._has_package = has_package
        self._max_age_ms = max_age_ms

    def _snapshot(self) -> CatalogSnapshot:
        snapshot = self._store.load()
        if snapshot is None or snapshot.index is None:
            snapshot = CatalogSnapshot(
                self._bundled(), BUNDLED_SOURCE, None, snapshot.error if snapshot else None
            )
            self._store.save(snapshot)
        return snapshot

    def _view(self, snapshot: CatalogSnapshot) -> CatalogView:
        known = {p.legacy_id or p.id for p in self._admin.list()}
        entries = snapshot.index.plugins if snapshot.index else ()
        plugins = [
            AvailablePlugin(e, installable(e.plugin, self._sdk_version, self._has_package))
            for e in entries
            if e.plugin.id not in known
        ]
        plugins.sort(key=lambda a: a.entry.plugin.name.lower())
        fetched = snapshot.fetched_at_ms
        stale = fetched is None or self._clock.now_ms() - fetched > self._max_age_ms
        return CatalogView(snapshot.source, fetched, snapshot.error, stale, plugins)

    def view(self) -> CatalogView:
        return self._view(self._snapshot())

    def refresh(self) -> CatalogView:
        old = self._snapshot()
        try:
            index = self._fetcher.fetch()
        except CatalogUnavailableError as exc:
            snapshot = CatalogSnapshot(old.index, old.source, old.fetched_at_ms, str(exc))
        else:
            snapshot = CatalogSnapshot(index, self._fetcher.source, self._clock.now_ms(), None)
        self._store.save(snapshot)
        return self._view(snapshot)

    def entry(self, plugin_id: str) -> CatalogEntry:
        index = self._snapshot().index
        for entry in index.plugins if index else ():
            if entry.plugin.id == plugin_id:
                return entry
        raise NotFoundError(f"unknown plugin {plugin_id!r}")

    def index(self) -> PluginIndex | None:
        return self._snapshot().index
