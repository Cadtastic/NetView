import sqlite3
from datetime import date
from pathlib import Path

import pytest
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


def test_backup_of_a_path_with_uri_characters(tmp_path: Path) -> None:
    folder = tmp_path / "a#b%20c%d"
    folder.mkdir()
    path = folder / "netview.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('0005')")
    con.execute("CREATE TABLE plugin_state (plugin_id TEXT)")
    con.execute("INSERT INTO plugin_state VALUES ('roku')")
    con.commit()
    con.close()

    made = backup_before_plugin_identity(path, TODAY)

    assert made is not None
    assert made.is_file()
    con = sqlite3.connect(made)
    try:
        assert con.execute("SELECT plugin_id FROM plugin_state").fetchall() == [("roku",)]
    finally:
        con.close()


def test_unreadable_database_does_not_crash_the_backup(tmp_path: Path) -> None:
    path = tmp_path / "netview.db"
    path.write_bytes(b"this is not a sqlite database" * 100)

    assert backup_before_plugin_identity(path, TODAY) is None


def test_a_killed_backup_does_not_suppress_the_next_one(tmp_path: Path) -> None:
    path = _db_at(tmp_path, "0005")
    stale = tmp_path / "netview.db.bak-2026-11-12-before-plugin-identity.part"
    stale.write_bytes(b"half a backup")

    made = backup_before_plugin_identity(path, TODAY)

    assert made is not None
    assert not stale.exists()
    con = sqlite3.connect(made)
    try:
        assert con.execute("SELECT plugin_id FROM plugin_state").fetchall() == [("roku",)]
    finally:
        con.close()


def test_backup_appears_under_its_name_only_when_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _db_at(tmp_path, "0005")

    def die(self: Path, target: object) -> Path:
        raise OSError("killed")

    monkeypatch.setattr(Path, "replace", die)
    with pytest.raises(OSError, match="killed"):
        backup_before_plugin_identity(path, TODAY)
    monkeypatch.undo()

    assert [p.name for p in tmp_path.iterdir() if ".bak-" in p.name] == []
    assert backup_before_plugin_identity(path, TODAY) is not None
