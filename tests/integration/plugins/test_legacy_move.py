import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from conftest import HostEnv

from netview.infrastructure.db.engine import make_engine, plugin_data_file
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.plugins import legacy
from netview.infrastructure.plugins.discovery import import_folder
from netview.infrastructure.plugins.legacy import LEGACY_PLUGIN_GUIDS, move_legacy_plugin_tables

PLUGINS = Path(__file__).resolve().parents[3] / "plugins"
GSM = LEGACY_PLUGIN_GUIDS["gsm7248"]
ROKU = LEGACY_PLUGIN_GUIDS["roku"]

# the plugins' own CREATE statements as their old (prefixed) migrations emitted them
GSM_PORT_SAMPLES = """CREATE TABLE gsm7248_port_samples (
	switch_id VARCHAR NOT NULL,
	if_index INTEGER NOT NULL,
	resolution VARCHAR NOT NULL,
	t_ms BIGINT NOT NULL,
	in_octets BIGINT NOT NULL,
	out_octets BIGINT NOT NULL,
	in_bps FLOAT,
	out_bps FLOAT,
	in_err_ps FLOAT,
	out_err_ps FLOAT,
	in_disc_ps FLOAT,
	out_disc_ps FLOAT,
	util_percent FLOAT,
	PRIMARY KEY (switch_id, if_index, resolution, t_ms)
)"""
GSM_MAC_LOCATIONS = """CREATE TABLE gsm7248_mac_locations (
	switch_id VARCHAR NOT NULL,
	mac VARCHAR NOT NULL,
	vlan INTEGER NOT NULL,
	if_index INTEGER NOT NULL,
	first_ms BIGINT NOT NULL,
	last_ms BIGINT NOT NULL,
	PRIMARY KEY (switch_id, mac, vlan, if_index)
)"""
GSM_INDEX = "CREATE INDEX ix_gsm7248_mac_locations_mac ON gsm7248_mac_locations (switch_id, mac)"
GSM_SNAPSHOTS = """CREATE TABLE gsm7248_snapshots (
	switch_id VARCHAR NOT NULL,
	t_ms BIGINT NOT NULL,
	body TEXT NOT NULL,
	PRIMARY KEY (switch_id)
)"""
ROKU_TVS = """CREATE TABLE roku_tvs (
	id VARCHAR NOT NULL,
	serial VARCHAR NOT NULL,
	ip VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	label VARCHAR NOT NULL,
	model VARCHAR NOT NULL,
	location VARCHAR NOT NULL,
	tv BOOLEAN NOT NULL,
	found_by VARCHAR NOT NULL,
	first_seen VARCHAR NOT NULL,
	last_seen VARCHAR NOT NULL,
	position INTEGER NOT NULL,
	PRIMARY KEY (id)
)"""
VERSION = (
    "CREATE TABLE alembic_version_{0} (version_num VARCHAR(32) NOT NULL, "
    "CONSTRAINT alembic_version_{0}_pkc PRIMARY KEY (version_num))"
)


def _legacy_core(path: Path) -> None:
    """A migrated ``netview.db`` that also holds the old prefixed tables of gsm7248 and roku."""
    engine = make_engine(f"sqlite:///{path}")
    upgrade_core(engine)
    engine.dispose()
    with closing(sqlite3.connect(path)) as con:
        for sql in (GSM_PORT_SAMPLES, GSM_MAC_LOCATIONS, GSM_INDEX, GSM_SNAPSHOTS, ROKU_TVS):
            con.execute(sql)
        con.execute(VERSION.format("gsm7248"))
        con.execute(VERSION.format("roku"))
        con.execute("INSERT INTO alembic_version_gsm7248 VALUES ('gsm7248_0001')")
        con.execute("INSERT INTO alembic_version_roku VALUES ('roku_0001')")
        con.executemany(
            "INSERT INTO gsm7248_port_samples (switch_id, if_index, resolution, t_ms, in_octets, out_octets)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [("sw", 1, "fast", 1000, 5, 6), ("sw", 2, "fast", 2000, 7, 8)],
        )
        con.execute("INSERT INTO gsm7248_mac_locations VALUES ('sw', 'aa', 1, 1, 1, 2)")
        con.execute(
            "INSERT INTO roku_tvs VALUES ('r1', 's', '1.2.3.4', 'n', 'l', 'm', 'loc', 1, 'f', 'a', 'b', 0)"
        )
        con.commit()


def _names(path: Path, kind: str = "table") -> set[str]:
    with closing(sqlite3.connect(path)) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as con:
        return con.execute(sql).fetchall()


@pytest.fixture
def core_db(tmp_path: Path) -> Path:
    path = tmp_path / "netview.db"
    _legacy_core(path)
    return path


def test_moves_tables_and_rows(core_db: Path, tmp_path: Path) -> None:
    result = move_legacy_plugin_tables(core_db, tmp_path)

    assert sorted(result.moved) == ["gsm7248", "roku"]
    assert result.failed == {}
    gsm = plugin_data_file(tmp_path, GSM)
    assert _names(gsm) == {"port_samples", "mac_locations", "snapshots", "alembic_version"}
    assert _rows(gsm, "SELECT COUNT(*) FROM port_samples") == [(2,)]
    assert _rows(gsm, "SELECT COUNT(*) FROM mac_locations") == [(1,)]
    assert _names(gsm, "index") >= {"ix_mac_locations_mac"}
    assert _rows(gsm, "SELECT sql FROM sqlite_master WHERE name = 'ix_mac_locations_mac'") == [
        ('CREATE INDEX "ix_mac_locations_mac" ON "mac_locations" (switch_id, mac)',)
    ]
    assert _rows(gsm, "SELECT version_num FROM alembic_version") == [("gsm7248_0001",)]
    assert _rows(plugin_data_file(tmp_path, ROKU), "SELECT id FROM tvs") == [("r1",)]
    left = _names(core_db)
    assert not [n for n in left if n.startswith(("gsm7248_", "roku_", "alembic_version_"))]
    assert "devices" in left  # the core is untouched
    assert not list((tmp_path / "plugin-data").glob("*.part"))


def test_rerun_is_noop(core_db: Path, tmp_path: Path) -> None:
    assert move_legacy_plugin_tables(core_db, tmp_path).moved
    again = move_legacy_plugin_tables(core_db, tmp_path)
    assert again.moved == []
    assert again.failed == {}


def test_move_failure_leaves_core_db_untouched(
    core_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _names(core_db)
    real = legacy._copy_rows
    calls: list[str] = []

    def flaky(src: sqlite3.Connection, dst: sqlite3.Connection, old: str, new: str) -> int:
        calls.append(old)
        if len(calls) == 2:
            raise RuntimeError("disk on fire")
        return real(src, dst, old, new)

    monkeypatch.setattr(legacy, "_copy_rows", flaky)

    result = move_legacy_plugin_tables(core_db, tmp_path, {"gsm7248": GSM})

    assert result.moved == []
    assert result.failed == {"gsm7248": "disk on fire"}
    assert _names(core_db) == before
    assert _rows(core_db, "SELECT COUNT(*) FROM gsm7248_port_samples") == [(2,)]
    assert not plugin_data_file(tmp_path, GSM).exists()
    assert not list((tmp_path / "plugin-data").glob("*.part*"))
    monkeypatch.undo()
    assert move_legacy_plugin_tables(core_db, tmp_path, {"gsm7248": GSM}).moved == ["gsm7248"]


def test_failure_of_one_id_does_not_stop_the_next(
    core_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = legacy._copy_rows

    def flaky(src: sqlite3.Connection, dst: sqlite3.Connection, old: str, new: str) -> int:
        if old == "gsm7248_snapshots":
            raise RuntimeError("boom")
        return real(src, dst, old, new)

    monkeypatch.setattr(legacy, "_copy_rows", flaky)

    result = move_legacy_plugin_tables(core_db, tmp_path)

    assert result.moved == ["roku"]
    assert list(result.failed) == ["gsm7248"]


def test_existing_file_skips(core_db: Path, tmp_path: Path) -> None:
    existing = plugin_data_file(tmp_path, GSM)
    existing.parent.mkdir()
    existing.write_bytes(b"")

    result = move_legacy_plugin_tables(core_db, tmp_path, {"gsm7248": GSM})

    assert result.moved == []
    assert result.failed == {}
    assert existing.read_bytes() == b""
    assert "gsm7248_port_samples" in _names(core_db)


def test_core_tables_that_start_with_an_id_are_not_moved(core_db: Path, tmp_path: Path) -> None:
    assert "inspection_reports" in _names(core_db)

    result = move_legacy_plugin_tables(core_db, tmp_path)

    assert "inspection" not in result.moved
    assert "inspection_reports" in _names(core_db)
    assert not plugin_data_file(tmp_path, LEGACY_PLUGIN_GUIDS["inspection"]).exists()


@pytest.fixture
def env(tmp_path: Path, core_db: Path) -> Iterator[HostEnv]:
    engine = make_engine(f"sqlite:///{core_db}")
    yield HostEnv(engine, tmp_path)
    engine.dispose()


def test_plugin_loads_on_moved_data(env: HostEnv, core_db: Path) -> None:
    assert move_legacy_plugin_tables(core_db, env.data_dir).moved

    host = env.host([], extra=[import_folder(PLUGINS / "gsm7248", 1)])
    host.load_all()

    info = host.get(env.id_of(GSM))
    assert info.state == "active", info.error
    gsm = plugin_data_file(env.data_dir, GSM)
    assert _rows(gsm, "SELECT version_num FROM alembic_version") == [("gsm7248_0001",)]
    assert _rows(gsm, "SELECT COUNT(*) FROM port_samples") == [(2,)]
    host.shutdown()


def test_failed_move_keeps_the_plugin_unloaded_and_the_data_in_place(
    env: HostEnv, core_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object) -> int:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(legacy, "_copy_rows", boom)
    result = move_legacy_plugin_tables(core_db, env.data_dir, {"gsm7248": GSM})
    assert list(result.failed) == ["gsm7248"]

    host = env.host(
        [], extra=[import_folder(PLUGINS / "gsm7248", 1)], blocked={GSM: result.failed["gsm7248"]}
    )
    host.load_all()

    info = host.get(env.id_of(GSM))
    assert info.state == "failed"
    assert info.error == "Moving its saved data failed: disk on fire. NetView retries at the next start."
    assert not plugin_data_file(env.data_dir, GSM).exists()
    assert "gsm7248_port_samples" in _names(core_db)
    assert host.routers() == []
