from collections.abc import Callable

import pytest

from netview.application.ports.auth_store import AuthStore
from netview.infrastructure.auth.memory_store import InMemoryAuthStore

FACTORIES: dict[str, Callable[[], AuthStore]] = {
    "memory": InMemoryAuthStore,
}


@pytest.fixture(params=list(FACTORIES))
def store_factory(request: pytest.FixtureRequest) -> Callable[[], AuthStore]:
    return FACTORIES[request.param]
