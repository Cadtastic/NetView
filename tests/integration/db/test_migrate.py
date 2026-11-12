import json
from pathlib import Path

from sqlalchemy import inspect, text

from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core, upgrade_plugin

CORE_TABLES = {
    "devices",
    "name_claims",
    "type_claims",
    "hints",
    "nicknames",
    "nickname_history",
    "watches",
    "events",
    "inspection_reports",
    "plugin_state",
    "plugin_catalog_cache",
    "users",
    "user_logins",
    "roles",
    "role_permissions",
    "user_roles",
    "sessions",
    "app_settings",
    "plugin_registry",
    "plugin_uninstall_pending",
}

DEMO_MIGRATION = """
import sqlalchemy as sa
from alembic import op

revision = "demo0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("demo_items", sa.Column("id", sa.Integer, primary_key=True))


def downgrade() -> None:
    op.drop_table("demo_items")
"""


def test_make_engine_creates_parent_folder_and_sets_pragmas(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'sub' / 'dir' / 'n.db'}")
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert (tmp_path / "sub" / "dir").is_dir()


def test_upgrade_core_creates_tables_and_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    upgrade_core(engine)
    names = set(inspect(engine).get_table_names())
    assert names >= CORE_TABLES
    with engine.connect() as c:
        rows = c.execute(text("SELECT version_num FROM alembic_version")).all()
    assert [r[0] for r in rows] == ["0006"]


def test_core_upgrade_indexes_inspection_reports_by_ip_and_id(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes("inspection_reports")}
    assert indexes["ix_inspection_reports_ip_id"] == ["ip", "id"]


def test_a_database_at_the_first_revision_upgrades_to_the_index(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    with engine.begin() as c:  # put the database back to revision 0001
        c.execute(text("DROP INDEX ix_inspection_reports_ip_id"))
        c.execute(text("DROP TABLE plugin_catalog_cache"))
        for table in (
            "plugin_uninstall_pending",
            "plugin_registry",
            "app_settings",
            "sessions",
            "user_roles",
            "role_permissions",
            "roles",
            "user_logins",
            "users",
        ):
            c.execute(text(f"DROP TABLE {table}"))
        c.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    upgrade_core(engine)
    names = {i["name"] for i in inspect(engine).get_indexes("inspection_reports")}
    assert {"ix_inspection_reports_ip", "ix_inspection_reports_ip_id"} <= names
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0006"


def test_plugin_upgrade_uses_own_version_table(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    versions = tmp_path / "demo_versions"
    versions.mkdir()
    (versions / "0001_demo.py").write_text(DEMO_MIGRATION, encoding="utf-8")

    upgrade_plugin(engine, "demo", versions)
    upgrade_plugin(engine, "demo", versions)

    names = set(inspect(engine).get_table_names())
    assert {"demo_items", "alembic_version_demo", "alembic_version"} <= names
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == ["0006"]
        assert c.execute(text("SELECT version_num FROM alembic_version_demo")).scalars().all() == ["demo0001"]


def test_migrate_creates_registry_tables(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    insp = inspect(engine)
    registry = {c["name"]: c for c in insp.get_columns("plugin_registry")}
    assert set(registry) == {"source_id", "guid", "last_folder"}
    assert registry["guid"]["nullable"] is False
    assert registry["last_folder"]["nullable"] is True
    assert [c["name"] for c in insp.get_columns("plugin_uninstall_pending")] == ["folder"]
    with engine.connect() as c:
        ddl = c.execute(text("SELECT sql FROM sqlite_master WHERE name = 'plugin_registry'")).scalar()
    assert ddl is not None and "AUTOINCREMENT" in ddl.upper()
    assert {tuple(u["column_names"]) for u in insp.get_unique_constraints("plugin_registry")} == {("guid",)}


ROKU_GUID = "241d4d28-4a70-406c-833c-a7b4d5b389a9"
INSPECTION_GUID = "ac1dc07d-123c-4414-a4c8-72013d00f267"
GSM7248_GUID = "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4"


def test_migration_0006_rekeys(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine, "0005")
    sections = [
        {"plugin_id": "inspection", "id": "summary", "title": "Summary", "data": {}, "error": None},
        {"plugin_id": "mystery", "id": "x", "title": "X", "data": {}, "error": None},
    ]
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO plugin_state (plugin_id, enabled, settings_json) "
                "VALUES ('roku', 1, '{\"a\": 1}')"
            )
        )
        c.execute(
            text("INSERT INTO plugin_state (plugin_id, enabled, settings_json) VALUES ('mystery', 1, '{}')")
        )
        c.execute(
            text(
                "INSERT INTO inspection_reports (ip, ports_spec, started_ms, finished_ms, sections_json) "
                "VALUES ('10.0.0.5', 'top', 1, 2, :j)"
            ),
            {"j": json.dumps(sections)},
        )
        c.execute(text("INSERT INTO roles (id, name, builtin) VALUES ('r1', 'R1', 0)"))
        for permission in ("gsm7248.console", "gsm7248.view", "core.view", "mystery.view"):
            c.execute(
                text("INSERT INTO role_permissions (role_id, permission_id) VALUES ('r1', :p)"),
                {"p": permission},
            )

    upgrade_core(engine)

    with engine.connect() as c:
        states = dict(c.execute(text("SELECT plugin_id, settings_json FROM plugin_state")).all())
        assert states == {ROKU_GUID: '{"a": 1}', "mystery": "{}"}
        stored = json.loads(c.execute(text("SELECT sections_json FROM inspection_reports")).scalar_one())
        assert [s["plugin_id"] for s in stored] == [INSPECTION_GUID, "mystery"]
        perms = set(
            c.execute(text("SELECT permission_id FROM role_permissions WHERE role_id = 'r1'")).scalars()
        )
        assert perms == {f"{GSM7248_GUID}.console", f"{GSM7248_GUID}.view", "core.view", "mystery.view"}


def test_migration_0006_is_a_noop_on_a_fresh_database(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM plugin_state")).scalar() == 0


def test_migration_0006_legacy_map_matches_the_fixed_guids() -> None:
    import importlib.util

    path = Path(__file__).parents[3] / "src/netview/infrastructure/db/core_versions/0006_plugin_guid_keys.py"
    spec = importlib.util.spec_from_file_location("m0006", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.LEGACY_GUIDS) == 9
    assert module.LEGACY_GUIDS["roku"] == ROKU_GUID
    assert len(set(module.LEGACY_GUIDS.values())) == 9
