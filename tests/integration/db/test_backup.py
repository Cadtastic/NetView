import sqlite3
from datetime import date
from pathlib import Path

from sqlalchemy import text

from netview.infrastructure.db.backup import backup_before_plugin_identity
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core

TODAY = date(2026, 11, 12)


def _db_at(tmp_path: Path, revision: str) -> Path:
    path = tmp_path / "netview.db"
    engine = make_engine(f"sqlite:///{path}")
    upgrade_core(engine, revision)
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO plugin_state (plugin_id, enabled, settings_json) VALUES ('roku', 1, '{}')")
        )
    engine.dispose()
    return path


def test_backup_made_once(tmp_path: Path) -> None:
    path = _db_at(tmp_path, "0005")

    made = backup_before_plugin_identity(path, TODAY)

    assert made == tmp_path / "netview.db.bak-2026-11-12-before-plugin-identity"
    assert made.is_file()
    con = sqlite3.connect(made)
    try:
        assert con.execute("SELECT plugin_id FROM plugin_state").fetchall() == [("roku",)]
    finally:
        con.close()

    before = made.stat().st_mtime_ns
    assert backup_before_plugin_identity(path, TODAY) is None
    assert made.stat().st_mtime_ns == before


def test_backup_skipped_when_already_migrated(tmp_path: Path) -> None:
    path = _db_at(tmp_path, "head")
    assert backup_before_plugin_identity(path, TODAY) is None
    assert [p.name for p in tmp_path.iterdir() if ".bak-" in p.name] == []


def test_backup_skipped_when_there_is_no_database(tmp_path: Path) -> None:
    assert backup_before_plugin_identity(tmp_path / "netview.db", TODAY) is None
    assert list(tmp_path.iterdir()) == []


def test_backup_skipped_for_a_database_the_migrations_never_touched(tmp_path: Path) -> None:
    path = tmp_path / "netview.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    assert backup_before_plugin_identity(path, TODAY) is None
