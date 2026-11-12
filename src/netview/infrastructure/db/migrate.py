"""Programmatic Alembic runner for the core schema and per-plugin schemas."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

_HERE = Path(__file__).parent
_SCRIPT_LOCATION = _HERE / "alembic_env"
_CORE_VERSIONS = _HERE / "core_versions"


def _upgrade(engine: Engine, versions_dir: Path, version_table: str, revision: str = "head") -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("version_locations", str(versions_dir))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        cfg.attributes["version_table"] = version_table
        command.upgrade(cfg, revision)


def upgrade_core(engine: Engine, revision: str = "head") -> None:
    """Bring the core schema up to ``revision`` (the newest by default)."""
    _upgrade(engine, _CORE_VERSIONS, "alembic_version", revision)


def upgrade_plugin(engine: Engine, plugin_id: str, versions_dir: Path) -> None:
    _upgrade(engine, versions_dir, f"alembic_version_{plugin_id}")
