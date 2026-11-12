from pathlib import Path

from sqlalchemy.orm import sessionmaker

from netview.application.plugins.plugin_json import (
    DEFAULT_ARCHIVE_URL,
    CatalogEntry,
    PluginJson,
    build_index,
)
from netview.application.ports.plugin_catalog import CatalogSnapshot
from netview.infrastructure.db.catalog_store import SqlCatalogStore
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.models import PluginCatalogCacheRow


def _store(tmp_path: Path) -> SqlCatalogStore:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    return SqlCatalogStore(sessionmaker(engine))


def test_load_empty_is_none(tmp_path: Path) -> None:
    assert _store(tmp_path).load() is None


def test_save_load_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pj = PluginJson(
        "Demo",
        "1.0.0",
        "d",
        "27bd9bf5-8dd2-4f12-bbe8-cfa490e3f85c",
        "Demo",
        "other",
        ">=2.0,<3",
        ("api",),
        ("api",),
    )
    index = build_index([CatalogEntry(pj, "plugins/demo")], "main", DEFAULT_ARCHIVE_URL)
    store.save(CatalogSnapshot(index, "https://example.test/i.json", 123, None))
    assert store.load() == CatalogSnapshot(index, "https://example.test/i.json", 123, None)
    store.save(CatalogSnapshot(index, "https://example.test/i.json", 123, "Couldn't reach GitHub"))
    loaded = store.load()
    assert loaded is not None and loaded.error == "Couldn't reach GitHub"


def test_cached_index_of_the_old_schema_is_treated_as_empty(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pj = PluginJson(
        "Demo", "1.0.0", "d", "27bd9bf5-8dd2-4f12-bbe8-cfa490e3f85c", "Demo", "other", ">=2.0,<3", (), ()
    )
    index = build_index([CatalogEntry(pj, "plugins/demo")], "main", DEFAULT_ARCHIVE_URL)
    store.save(CatalogSnapshot(index, "https://example.test/i.json", 1, None))
    with store._sessions() as session:
        row = session.get(PluginCatalogCacheRow, 1)
        assert row is not None and row.payload is not None
        row.payload = row.payload.replace("netview.plugin-index/2", "netview.plugin-index/1")
        session.commit()
    loaded = store.load()
    assert loaded is not None and loaded.index is None
