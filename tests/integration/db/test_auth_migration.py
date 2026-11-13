import threading
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from netview.domain.auth import ADMIN_ROLE, DEFAULT_ROLE, User
from netview.domain.errors import ConflictError
from netview.infrastructure.auth.sql_store import SqlAuthStore, SqlUserRepository
from netview.infrastructure.db import migrate
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core


def _user(username: str, *, builtin: bool = False) -> User:
    return User(
        id=0,
        username=username,
        display_name=username,
        email=None,
        enabled=True,
        builtin=builtin,
        must_change_password=False,
        role_ids=frozenset(),
        provider="local",
        created_ms=1,
        last_sign_in_ms=None,
    )


def _upgrade_to(engine: Engine, revision: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrate._SCRIPT_LOCATION))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("version_locations", str(migrate._CORE_VERSIONS))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        cfg.attributes["version_table"] = "alembic_version"
        command.upgrade(cfg, revision)


def test_upgrade_from_0003_keeps_data_and_seeds_roles(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    _upgrade_to(engine, "0003")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO devices"
                " (key, ip, vendor, first_seen_ms, last_seen_ms, status, is_self, missed, is_new)"
                " VALUES ('k1', '10.0.0.5', '', 1, 2, 'up', 0, 0, 0)"
            )
        )
    upgrade_core(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT ip FROM devices WHERE key = 'k1'")).scalar() == "10.0.0.5"
        roles = c.execute(text("SELECT id, name, builtin FROM roles ORDER BY id")).all()
        assert [(r[0], r[1], bool(r[2])) for r in roles] == [
            (ADMIN_ROLE, "Administrator", True),
            (DEFAULT_ROLE, "Default", True),
        ]
        perms = c.execute(text("SELECT role_id, permission_id FROM role_permissions")).all()
        assert [tuple(r) for r in perms] == [(DEFAULT_ROLE, "core.view")]
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0006"


def test_racing_setup_inserts_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    store = SqlAuthStore(sessionmaker(engine))
    barrier = threading.Barrier(8)
    real_count = SqlUserRepository.count

    def slow_count(self: SqlUserRepository) -> int:
        n = real_count(self)
        time.sleep(0.02)  # widen the gap between the count and the insert
        return n

    monkeypatch.setattr(SqlUserRepository, "count", slow_count)
    outcomes: list[str] = []

    def attempt(i: int) -> None:
        barrier.wait()
        try:
            with store() as uow:
                uow.users.add(_user(f"admin{i}"), "h", only_if_empty=True)
                uow.commit()
            outcomes.append("ok")
        except ConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Ordinary users: neither the username check nor the one-built-in index can produce this result,
    # only the count-then-insert being atomic under BEGIN IMMEDIATE.
    assert sorted(outcomes) == ["conflict"] * 7 + ["ok"]
    with store() as uow:
        assert uow.users.count() == 1


def test_racing_setup_inserts_would_overshoot_without_begin_immediate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: on a plain engine the same race admits more than one user."""
    from sqlalchemy import create_engine

    path = tmp_path / "n.db"
    upgrade_core(make_engine(f"sqlite:///{path}"))
    plain = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 5})
    store = SqlAuthStore(sessionmaker(plain))
    barrier = threading.Barrier(8)
    real_count = SqlUserRepository.count

    def slow_count(self: SqlUserRepository) -> int:
        n = real_count(self)
        time.sleep(0.05)
        return n

    monkeypatch.setattr(SqlUserRepository, "count", slow_count)
    outcomes: list[str] = []

    def attempt(i: int) -> None:
        barrier.wait()
        try:
            with store() as uow:
                uow.users.add(_user(f"admin{i}"), "h", only_if_empty=True)
                uow.commit()
            outcomes.append("ok")
        except Exception:
            outcomes.append("error")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") > 1


def test_one_builtin_index_allows_ordinary_users(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    store = SqlAuthStore(sessionmaker(engine))
    with store() as uow:
        for i in range(5):
            uow.users.add(_user(f"user{i}"), None)
        uow.commit()
    with store() as uow:
        assert uow.users.count() == 5
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO users (username, display_name, builtin, created_ms) VALUES ('b1', 'b1', 1, 1)")
        )
    with engine.connect() as c, pytest.raises(Exception, match="UNIQUE"):
        c.execute(
            text("INSERT INTO users (username, display_name, builtin, created_ms) VALUES ('b2', 'b2', 1, 1)")
        )
    with store() as uow, pytest.raises(ConflictError):
        uow.users.add(_user("b3", builtin=True), None)


def test_one_builtin_index_violation_becomes_conflict_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    store = SqlAuthStore(sessionmaker(engine))
    with store() as uow:
        uow.users.add(_user("b1", builtin=True), None)
        uow.commit()
    # Skip the Python pre-check so the unique index itself is what rejects the row.
    monkeypatch.setattr(SqlUserRepository, "_builtin_exists", lambda self: False)
    with pytest.raises(ConflictError, match="setup already done"), store() as uow:
        uow.users.add(_user("b2", builtin=True), None)
        uow.commit()
