from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from netview.application.ports.repositories import PluginState
from netview.application.ports.uow import UnitOfWorkFactory
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.sdk.testing.fakes import InMemoryUnitOfWorkFactory

GUID_A = "4eddf684-deb5-41cf-9588-020746307ade"
GUID_B = "9f4cd689-1a67-4c89-abff-ac9252568d97"


def _sql_factory(path: Path) -> UnitOfWorkFactory:
    engine = make_engine(f"sqlite:///{path}")
    upgrade_core(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return lambda: SqlUnitOfWork(sessions)


@pytest.fixture(params=["sql", "memory"])
def factory(request: pytest.FixtureRequest, tmp_path: Path) -> UnitOfWorkFactory:
    if request.param == "sql":
        return _sql_factory(tmp_path / "netview.db")
    return InMemoryUnitOfWorkFactory()


def test_assign_is_stable(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        first = uow.plugin_registry.assign(GUID_A)
        again = uow.plugin_registry.assign(GUID_A)
        other = uow.plugin_registry.assign(GUID_B)
        uow.commit()
    assert first == again
    assert other != first
    with factory() as uow:
        assert uow.plugin_registry.source_id(GUID_A) == first
        assert uow.plugin_registry.source_id(GUID_B) == other
        assert uow.plugin_registry.source_id("00000000-0000-0000-0000-000000000000") is None


def test_source_id_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "netview.db"
    with _sql_factory(path)() as uow:
        first = uow.plugin_registry.assign(GUID_A)
        uow.commit()
    with _sql_factory(path)() as uow:
        assert uow.plugin_registry.assign(GUID_A) == first
        assert uow.plugin_registry.source_id(GUID_A) == first


def test_registry_row_never_deleted_by_state_delete(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        sid = uow.plugin_registry.assign(GUID_A)
        uow.plugin_state.save(PluginState(GUID_A, True, {}, None))
        uow.commit()
    with factory() as uow:
        uow.plugin_state.delete(GUID_A)
        uow.plugin_state.delete("never-existed")
        uow.commit()
    with factory() as uow:
        assert uow.plugin_state.get(GUID_A) is None
        assert uow.plugin_registry.source_id(GUID_A) == sid


def test_pending_uninstall_round_trip(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        assert uow.plugin_registry.pending_uninstalls() == []
        uow.plugin_registry.add_pending_uninstall("C:/data/plugins/a")
        uow.plugin_registry.add_pending_uninstall("C:/data/plugins/a")
        uow.plugin_registry.add_pending_uninstall("C:/data/plugins/b")
        uow.commit()
    with factory() as uow:
        assert sorted(uow.plugin_registry.pending_uninstalls()) == ["C:/data/plugins/a", "C:/data/plugins/b"]
        uow.plugin_registry.clear_pending_uninstall("C:/data/plugins/a")
        uow.plugin_registry.clear_pending_uninstall("C:/data/plugins/missing")
        uow.commit()
    with factory() as uow:
        assert uow.plugin_registry.pending_uninstalls() == ["C:/data/plugins/b"]


def test_last_folders_round_trip(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.plugin_registry.assign(GUID_A)
        uow.plugin_registry.assign(GUID_B)
        assert uow.plugin_registry.last_folders() == {}
        uow.plugin_registry.set_last_folder(GUID_A, "C:/x/a")
        uow.plugin_registry.set_last_folder(GUID_A, "C:/x/a2")
        uow.commit()
    with factory() as uow:
        assert uow.plugin_registry.last_folders() == {GUID_A: "C:/x/a2"}


def test_autoincrement_never_reuses_a_deleted_max_id(tmp_path: Path) -> None:
    from sqlalchemy import text

    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with SqlUnitOfWork(sessions) as uow:
        sid = uow.plugin_registry.assign(GUID_A)
        uow.commit()
    with engine.begin() as c:
        c.execute(text("DELETE FROM plugin_registry"))
    with SqlUnitOfWork(sessions) as uow:
        assert uow.plugin_registry.assign(GUID_B) > sid
