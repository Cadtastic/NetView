import uuid
from dataclasses import replace

from netview.application.plugins.plugin_json import (
    DEFAULT_ARCHIVE_URL,
    PluginIndex,
    PluginJson,
    build_index,
    installable,
)
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.ports.plugin_catalog import CatalogSnapshot
from netview.application.usecases.plugin_catalog import PluginCatalogService
from netview.domain.errors import CatalogUnavailableError
from netview.sdk.testing.fakes import FakeClock


def _pj(plugin_id: str, **kw: object) -> PluginJson:
    base = PluginJson(
        id=plugin_id,
        name=plugin_id.title(),
        version="0.1.0",
        description="d",
        guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, plugin_id)),
        display_name=plugin_id.title(),
        plugin_type="other",
        sdk_version=">=1.3,<2",
        capabilities=("api",),
        permissions=("api",),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _index(*ids: str) -> PluginIndex:
    return build_index([_pj(i) for i in ids], "main", DEFAULT_ARCHIVE_URL)


class MemStore:
    def __init__(self) -> None:
        self.snapshot: CatalogSnapshot | None = None

    def load(self) -> CatalogSnapshot | None:
        return self.snapshot

    def save(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot


class StubFetcher:
    source = "https://example.test/index.json"

    def __init__(self) -> None:
        self.result: PluginIndex | CatalogUnavailableError = _index("alpha", "beta")

    def fetch(self) -> PluginIndex:
        if isinstance(self.result, CatalogUnavailableError):
            raise self.result
        return self.result


class StubAdmin:
    def __init__(self, *infos: PluginInfo) -> None:
        self.infos = list(infos)

    def list(self) -> list[PluginInfo]:
        return self.infos


def _service(
    admin: StubAdmin | None = None,
    store: MemStore | None = None,
    fetcher: StubFetcher | None = None,
    clock: FakeClock | None = None,
) -> PluginCatalogService:
    return PluginCatalogService(
        store or MemStore(),
        fetcher or StubFetcher(),
        lambda: _index("alpha", "beta", "gamma"),
        admin or StubAdmin(),  # type: ignore[arg-type]
        clock or FakeClock(),
        "1.3",
        lambda name: True,
    )


def _ids(service: PluginCatalogService) -> list[str]:
    return [a.entry.plugin.id for a in service.view().plugins]


def test_view_seeds_from_bundled_when_empty() -> None:
    store = MemStore()
    view = _service(store=store).view()
    assert view.source == "bundled"
    assert view.stale is True
    assert view.fetched_at_ms is None
    assert _ids(_service(store=store)) == ["alpha", "beta", "gamma"]
    assert store.snapshot is not None


def test_view_excludes_installed_and_pending_ids() -> None:
    admin = StubAdmin(
        PluginInfo("alpha", "Alpha", "1", "d", "active"),
        PluginInfo("beta", "Beta", "1", "d", "pending"),
    )
    assert _ids(_service(admin=admin)) == ["gamma"]


def test_refresh_success_saves_and_clears_error() -> None:
    store = MemStore()
    clock = FakeClock()
    service = _service(store=store, clock=clock)
    view = service.refresh()
    assert view.error is None
    assert view.source == "https://example.test/index.json"
    assert view.fetched_at_ms == clock.now_ms()
    assert view.stale is False
    assert _ids(service) == ["alpha", "beta"]
    assert store.snapshot is not None and store.snapshot.error is None


def test_refresh_keeps_old_index_on_bad_payload() -> None:
    fetcher = StubFetcher()
    service = _service(fetcher=fetcher)
    service.refresh()
    message = "Couldn't read the plugin list (wrong schema)"
    fetcher.result = CatalogUnavailableError(message)
    view = service.refresh()
    assert view.error == message
    assert [a.entry.plugin.id for a in view.plugins] == ["alpha", "beta"]
    assert service.view().error == message


def test_refresh_failure_from_bundled_keeps_bundled_list() -> None:
    fetcher = StubFetcher()
    fetcher.result = CatalogUnavailableError("Couldn't reach GitHub")
    view = _service(fetcher=fetcher).refresh()
    assert view.error == "Couldn't reach GitHub"
    assert view.source == "bundled"
    assert len(view.plugins) == 3


def test_installable_reasons() -> None:
    assert installable(_pj("a", sdk_version=">=9"), "1.3", lambda n: True) == "Needs a newer netview"
    assert (
        installable(_pj("a", requires=("nopkg",)), "1.3", lambda n: False)
        == "Needs nopkg, which this netview does not have"
    )
    assert installable(_pj("a"), "1.3", lambda n: True) is None


def test_stale_after_one_hour() -> None:
    clock = FakeClock()
    service = _service(clock=clock)
    service.refresh()
    clock.advance(3_600_000)
    assert service.view().stale is False
    clock.advance(1)
    assert service.view().stale is True
