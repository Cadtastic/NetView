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
    assert [r[0] for r in rows] == ["0002"]


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
        c.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    upgrade_core(engine)
    names = {i["name"] for i in inspect(engine).get_indexes("inspection_reports")}
    assert {"ix_inspection_reports_ip", "ix_inspection_reports_ip_id"} <= names
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"


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
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == ["0002"]
        assert c.execute(text("SELECT version_num FROM alembic_version_demo")).scalars().all() == ["demo0001"]
