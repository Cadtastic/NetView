import threading

from netview.application.auth.principal import SYSTEM_PRINCIPAL, current_principal, get_principal
from netview.domain.auth import User
from netview.domain.errors import ConflictError
from netview.infrastructure.auth.memory_store import InMemoryAuthStore


def _admin(name: str) -> User:
    return User(0, name, name, None, True, True, False, frozenset(), "local", 1, None)


def test_racing_first_run_setups_create_one_admin():
    store = InMemoryAuthStore()
    barrier = threading.Barrier(8)
    wins: list[int] = []

    def attempt(i: int) -> None:
        with store() as uow:
            barrier.wait()
            try:
                uow.users.add(_admin(f"admin{i}"), "h", only_if_empty=True)
                uow.commit()
                wins.append(i)
            except ConflictError:
                pass

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    with store() as uow:
        assert uow.users.count() == 1


def test_principal_context_defaults_to_none():
    assert get_principal() is None
    token = current_principal.set(SYSTEM_PRINCIPAL)
    try:
        assert get_principal() is SYSTEM_PRINCIPAL
        assert SYSTEM_PRINCIPAL.can("anything")
    finally:
        current_principal.reset(token)
