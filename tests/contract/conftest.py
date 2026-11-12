from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from netview.application.ports.auth_store import AuthStore
from netview.infrastructure.auth.memory_store import InMemoryAuthStore
from netview.infrastructure.auth.sql_store import SqlAuthStore
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core


def _memory(_tmp: Path) -> Callable[[], AuthStore]:
    return InMemoryAuthStore


def _sql(tmp: Path) -> Callable[[], AuthStore]:
    def make() -> AuthStore:
        engine = make_engine(f"sqlite:///{tmp / 'contract.db'}")
        upgrade_core(engine)
        return SqlAuthStore(sessionmaker(engine))

    return make


FACTORIES: dict[str, Callable[[Path], Callable[[], AuthStore]]] = {"memory": _memory, "sql": _sql}


@pytest.fixture(params=list(FACTORIES))
def store_factory(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[], AuthStore]:
    return FACTORIES[request.param](tmp_path)
