import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from netview.infrastructure.db.backup import _readonly_uri, backup_before_plugin_identity
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


def test_revision_that_cannot_be_read_still_gets_a_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: if the read-only open fails, the database is backed up, not migrated unprotected."""
    path = _db_at(tmp_path, "0005")
    real = sqlite3.connect

    def refuse_uri(database: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        if str(database).startswith("file:"):
            raise sqlite3.OperationalError("invalid uri authority")
        return real(database, *args, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(sqlite3, "connect", refuse_uri)

    made = backup_before_plugin_identity(path, TODAY)

    assert made is not None
    monkeypatch.undo()
    con = sqlite3.connect(made)
    try:
        assert con.execute("SELECT plugin_id FROM plugin_state").fetchall() == [("roku",)]
    finally:
        con.close()


def test_uri_quoting_of_drive_and_unc_paths() -> None:
    assert _readonly_uri("C:/a b/x#y%z?.db") == "file:C:/a%20b/x%23y%25z%3F.db?mode=ro"
    assert _readonly_uri("//host/share/a#b.db") == "file:////host/share/a%23b.db?mode=ro"


@pytest.mark.skipif(sys.platform != "win32", reason="UNC paths")
def test_backup_through_a_unc_path(tmp_path: Path) -> None:
    path = _db_at(tmp_path, "0005")
    bs = chr(92)
    unc = Path(bs * 2 + "localhost" + bs + str(path)[0] + "$" + str(path)[2:])
    if not unc.exists():
        pytest.skip("administrative share not reachable")

    made = backup_before_plugin_identity(unc, TODAY)

    assert made is not None
    assert made.is_file()


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


def test_backup_taken_when_the_version_select_fails_for_another_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _db_at(tmp_path, "0005")
    real_connect = sqlite3.connect

    class Locked:
        def __init__(self, con: sqlite3.Connection) -> None:
            self._con = con

        def execute(self, sql: str, *args: object) -> object:
            if "alembic_version" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._con.execute(sql, *args)

        def close(self) -> None:
            self._con.close()

    def connect(target: object, *args: object, **kwargs: object) -> object:
        con = real_connect(target, *args, **kwargs)  # type: ignore[call-overload]
        return Locked(con) if kwargs.get("uri") else con

    monkeypatch.setattr("netview.infrastructure.db.backup.sqlite3.connect", connect)

    made = backup_before_plugin_identity(path, TODAY)

    assert made is not None and made.is_file()
