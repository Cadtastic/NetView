"""One-time move of the tables the plugins used to keep in ``netview.db`` into their own files.

Before plugins had a database file each, a plugin with storage kept ``<id>_*`` tables and an
``alembic_version_<id>`` version table in ``netview.db``. The move builds ``<guid>.db.part`` from them,
renames it to ``<guid>.db`` and only then drops the old tables, so a failure at any step leaves
``netview.db`` as it was.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from netview.infrastructure.db.engine import plugin_data_file

log = logging.getLogger(__name__)

LEGACY_PLUGIN_GUIDS: Mapping[str, str] = {
    "lan_discovery": "4eddf684-deb5-41cf-9588-020746307ade",
    "health": "9f4cd689-1a67-4c89-abff-ac9252568d97",
    "identity": "4b77e778-dc26-4ac0-8b2e-fe3995363df1",
    "inspection": "ac1dc07d-123c-4414-a4c8-72013d00f267",
    "local_host": "0a505ba4-bbbd-40b8-a77d-8f5dbe1470a8",
    "gsm7248": "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4",
    "gs105e": "c66a564b-0254-44cf-bb74-1c7f6ebae6be",
    "starlink": "67216b55-f454-4876-b26f-336e505c83ce",
    "roku": "241d4d28-4a70-406c-833c-a7b4d5b389a9",
}

_BATCH = 1000
_VERSION_TABLE_SQL = (
    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
)


@dataclass
class LegacyMoveResult:
    """What the move did: the legacy ids it moved, and the ones that failed with the reason."""

    moved: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _name_pattern(name: str) -> str:
    n = re.escape(name)
    return rf'(?:"{n}"|`{n}`|\[{n}\]|\b{n}\b)'


def _rename_table_sql(sql: str, renames: Mapping[str, str]) -> str:
    """Rewrite the CREATE TABLE header and any REFERENCES to a moved table."""
    for old, new in renames.items():
        sql = re.sub(
            rf"(?i)^(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?){_name_pattern(old)}",
            lambda m, n=new: m.group(1) + _ident(n),  # type: ignore[misc]
            sql,
            count=1,
        )
        sql = re.sub(
            rf"(?i)(\bREFERENCES\s+){_name_pattern(old)}",
            lambda m, n=new: m.group(1) + _ident(n),  # type: ignore[misc]
            sql,
        )
    return sql


def _rename_index_sql(sql: str, old_index: str, new_index: str, old_table: str, new_table: str) -> str:
    sql = re.sub(
        rf"(?i)^(\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?){_name_pattern(old_index)}",
        lambda m: m.group(1) + _ident(new_index),
        sql,
        count=1,
    )
    return re.sub(
        rf"(?i)(\bON\s+){_name_pattern(old_table)}", lambda m: m.group(1) + _ident(new_table), sql, count=1
    )


def _copy_rows(src: sqlite3.Connection, dst: sqlite3.Connection, old: str, new: str) -> int:
    """Copy every row of ``old`` (in ``src``) into ``new`` (in ``dst``); returns the row count."""
    cursor = src.execute(f"SELECT * FROM {_ident(old)}")
    width = len(cursor.description)
    insert = f"INSERT INTO {_ident(new)} VALUES ({', '.join('?' * width)})"
    count = 0
    while batch := cursor.fetchmany(_BATCH):
        dst.executemany(insert, batch)
        count += len(batch)
    return count


def _unlink_part(part: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(part) + suffix).unlink(missing_ok=True)


def _legacy_tables(core: sqlite3.Connection, legacy_id: str) -> tuple[list[str], str | None]:
    """The ``<id>_*`` tables and the version table of ``legacy_id``.

    Only an id that has its ``alembic_version_<id>`` table is moved: every plugin with storage had one, and
    it keeps the core's own tables that merely start with an id (``inspection_reports``) out of the move.
    """
    names = [r[0] for r in core.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    version = f"alembic_version_{legacy_id}"
    if version not in names:
        return [], None
    prefix = f"{legacy_id}_"
    return sorted(n for n in names if n.startswith(prefix)), version


def _build_part(
    core: sqlite3.Connection, part: Path, legacy_id: str, tables: list[str], version: str
) -> None:
    prefix = f"{legacy_id}_"
    renames = {t: t[len(prefix) :] for t in tables}
    with closing(sqlite3.connect(str(part))) as dst:
        dst.isolation_level = None
        dst.execute("BEGIN")
        core.execute("BEGIN")  # one snapshot of the old tables
        try:
            for old in renames:
                row = core.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (old,))
                dst.execute(_rename_table_sql(row.fetchone()[0], renames))
            marks = ", ".join("?" * len(tables))
            indexes = core.execute(
                "SELECT name, tbl_name, sql FROM sqlite_master "
                f"WHERE type = 'index' AND sql IS NOT NULL AND tbl_name IN ({marks}) ORDER BY name",
                tables,
            ).fetchall()
            for name, tbl, sql in indexes:
                new_name = name.replace(prefix, "", 1)
                dst.execute(_rename_index_sql(sql, name, new_name, tbl, renames[tbl]))
            for old, new in renames.items():
                copied = _copy_rows(core, dst, old, new)
                have = dst.execute(f"SELECT COUNT(*) FROM {_ident(new)}").fetchone()[0]
                if copied != have:
                    raise RuntimeError(f"copied {copied} rows of {old} but {have} arrived in {new}")
            dst.execute(_VERSION_TABLE_SQL)
            rows = core.execute(f"SELECT version_num FROM {_ident(version)}").fetchall()
            if not rows:
                raise RuntimeError(f"{version} has no version row")
            dst.executemany("INSERT INTO alembic_version (version_num) VALUES (?)", rows)
        finally:
            core.execute("ROLLBACK")  # the snapshot was read-only; this just ends it
        dst.execute("COMMIT")


def _move_one(core_db: Path, data_dir: Path, legacy_id: str, guid: str) -> bool:
    """Move one plugin; True when it moved, False when there was nothing to do. Raises on failure."""
    target = plugin_data_file(data_dir, guid)
    with closing(sqlite3.connect(str(core_db), timeout=30)) as core:
        core.isolation_level = None
        tables, version = _legacy_tables(core, legacy_id)
        if version is None:
            return False
        if target.exists():
            log.info("legacy tables of %s left in place: %s already exists", legacy_id, target.name)
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        _unlink_part(part)
        renamed = False
        try:
            _build_part(core, part, legacy_id, tables, version)
            part.replace(target)  # the connection to the part is closed by now
            renamed = True
            core.execute("BEGIN IMMEDIATE")
            try:
                for name in (*tables, version):
                    core.execute(f"DROP TABLE {_ident(name)}")
            except BaseException:
                core.execute("ROLLBACK")
                raise
            core.execute("COMMIT")
        except BaseException:
            _unlink_part(part)
            if renamed:
                target.unlink(missing_ok=True)  # the old tables are still there, so the next start retries
            raise
    return True


def move_legacy_plugin_tables(
    core_db: Path, data_dir: Path, legacy: Mapping[str, str] = LEGACY_PLUGIN_GUIDS
) -> LegacyMoveResult:
    """Move each legacy plugin's ``<id>_*`` tables out of ``core_db`` into its own data file.

    A plugin whose data file already exists is left alone. A failure for one id is logged and recorded in
    ``failed`` (the id with the error text); ``core_db`` is unchanged for that id and no data file is left.
    """
    result = LegacyMoveResult()
    if not core_db.is_file():
        return result
    for legacy_id, guid in legacy.items():
        try:
            if _move_one(core_db, data_dir, legacy_id, guid):
                result.moved.append(legacy_id)
                log.info("moved the saved data of %s into %s", legacy_id, plugin_data_file(data_dir, guid))
        except Exception as exc:
            log.exception("moving the saved data of %s failed", legacy_id)
            result.failed[legacy_id] = str(exc) or type(exc).__name__
    return result
