"""A plugin's own database file: its path, its engine and the one thing the engine denies."""

from pathlib import Path

import pytest
from sqlalchemy import text

from netview.infrastructure.db.engine import make_engine, make_plugin_engine, plugin_data_file

GUID = "6d7a1ca2-d5eb-4d9b-b861-7600f0fe7768"


def test_plugin_data_file_path(tmp_path: Path) -> None:
    assert plugin_data_file(tmp_path, GUID) == tmp_path / "plugin-data" / f"{GUID}.db"


def test_attach_denied(tmp_path: Path) -> None:
    core = make_engine(f"sqlite:///{tmp_path / 'netview.db'}")
    with core.begin() as c:
        c.execute(text("CREATE TABLE secret (id INTEGER)"))
    engine = make_plugin_engine(plugin_data_file(tmp_path, GUID))
    try:
        with engine.connect() as c, pytest.raises(Exception, match="not authorized"):
            c.exec_driver_sql(f"ATTACH DATABASE '{tmp_path / 'netview.db'}' AS c")
    finally:
        engine.dispose()
        core.dispose()


def test_plugin_engine_allows_ordinary_work_in_its_own_file(tmp_path: Path) -> None:
    path = plugin_data_file(tmp_path, GUID)
    engine = make_plugin_engine(path)
    try:
        with engine.begin() as c:
            c.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
            c.execute(text("CREATE INDEX ix_t ON t (id)"))
            c.execute(text("INSERT INTO t (id) VALUES (1)"))
            assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    finally:
        engine.dispose()
    assert path.is_file()
