from pathlib import Path

from sqlalchemy.orm import sessionmaker

from netview.application.plugins.plugin_json import DEFAULT_ARCHIVE_URL, PluginJson, build_index
from netview.application.ports.plugin_catalog import CatalogSnapshot
from netview.infrastructure.db.catalog_store import SqlCatalogStore
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core


def _store(tmp_path: Path) -> SqlCatalogStore:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    return SqlCatalogStore(sessionmaker(engine))


def test_load_empty_is_none(tmp_path: Path) -> None:
    assert _store(tmp_path).load() is None


def test_save_load_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pj = PluginJson(
        "demo",
        "Demo",
        "1.0.0",
        "d",
        "27bd9bf5-8dd2-4f12-bbe8-cfa490e3f85c",
        "Demo",
        "other",
        ">=1.3,<2",
        ("api",),
        ("api",),
    )
    index = build_index([pj], "main", DEFAULT_ARCHIVE_URL)
    store.save(CatalogSnapshot(index, "https://example.test/i.json", 123, None))
    assert store.load() == CatalogSnapshot(index, "https://example.test/i.json", 123, None)
    store.save(CatalogSnapshot(index, "https://example.test/i.json", 123, "Couldn't reach GitHub"))
    loaded = store.load()
    assert loaded is not None and loaded.error == "Couldn't reach GitHub"
