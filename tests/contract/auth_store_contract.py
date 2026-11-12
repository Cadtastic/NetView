"""Assertions every AuthStore implementation must satisfy. Each check takes a store factory."""

from collections.abc import Callable

import pytest

from netview.application.ports.auth_store import AuthStore, SessionRecord
from netview.domain.auth import ADMIN_ROLE, DEFAULT_ROLE, Role, User
from netview.domain.errors import ConflictError

StoreFactory = Callable[[], AuthStore]


def make_user(
    username: str = "admin", *, builtin: bool = False, role_ids: frozenset[str] = frozenset()
) -> User:
    return User(
        id=0,
        username=username,
        display_name=username.title(),
        email=None,
        enabled=True,
        builtin=builtin,
        must_change_password=False,
        role_ids=role_ids,
        provider="local",
        created_ms=1,
        last_sign_in_ms=None,
    )


def check_builtin_roles_exist(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        admin = uow.roles.get(ADMIN_ROLE)
        default = uow.roles.get(DEFAULT_ROLE)
        assert admin is not None and admin.builtin and admin.name == "Administrator"
        assert default is not None and default.builtin and default.permissions == frozenset({"core.view"})


def check_user_round_trip(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        added = uow.users.add(make_user("admin"), "hash1")
        uow.commit()
    assert added.id > 0
    with store() as uow:
        found = uow.users.by_username("ADMIN".lower())
        assert found is not None and found.id == added.id
        assert uow.users.get(added.id) == found
        assert uow.users.password_hash(added.id) == "hash1"
        assert uow.users.count() == 1
        assert [u.username for u in uow.users.list()] == ["admin"]


def check_duplicate_username_conflicts(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        uow.users.add(make_user("kim"), None)
        with pytest.raises(ConflictError):
            uow.users.add(make_user("kim"), None)


def check_role_removal_strips_users(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        uow.roles.add(Role("helpdesk", "Helpdesk", False, frozenset({"core.rename"})))
        user = uow.users.add(make_user("kim", role_ids=frozenset({"helpdesk", DEFAULT_ROLE})), None)
        uow.commit()
    with store() as uow:
        uow.roles.remove("helpdesk")
        uow.commit()
    with store() as uow:
        assert uow.roles.get("helpdesk") is None
        again = uow.users.get(user.id)
        assert again is not None and again.role_ids == frozenset({DEFAULT_ROLE})


def check_sessions(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        user = uow.users.add(make_user("kim"), None)
        for i in range(3):
            uow.sessions.add(SessionRecord(f"t{i}", user.id, 10, 10, "127.0.0.1", "ua"))
        uow.sessions.touch("t0", 99)
        uow.commit()
    with store() as uow:
        s = uow.sessions.get("t0")
        assert s is not None and s.last_seen_ms == 99
        uow.sessions.remove("t1")
        assert uow.sessions.get("t1") is None
        assert uow.sessions.remove_for_user(user.id) == 2
        assert uow.sessions.get("t2") is None


def check_security_version_round_trips(factory: StoreFactory) -> None:
    from dataclasses import replace

    store = factory()
    with store() as uow:
        user = uow.users.add(make_user("lee"), "h")
        assert user.security_version == 0
        uow.users.save(replace(user, security_version=3))
        uow.sessions.add(SessionRecord("tv", user.id, 1, 1, "127.0.0.1", "ua", security_version=3))
        uow.commit()
    with store() as uow:
        got = uow.users.get(user.id)
        assert got is not None and got.security_version == 3
        s = uow.sessions.get("tv")
        assert s is not None and s.security_version == 3


def check_settings(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        assert uow.settings.get("mode") is None
        uow.settings.set("mode", "home")
        uow.commit()
    with store() as uow:
        assert uow.settings.get("mode") == "home"


def check_nothing_persists_without_commit(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        uow.users.add(make_user("ghost"), None)
        uow.settings.set("k", "v")
    with store() as uow:
        assert uow.users.count() == 0
        assert uow.users.by_username("ghost") is None
        assert uow.settings.get("k") is None


def check_only_if_empty(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        uow.users.add(make_user("first", builtin=True), "h", only_if_empty=True)
        uow.commit()
    with store() as uow, pytest.raises(ConflictError):
        uow.users.add(make_user("second"), "h", only_if_empty=True)


def check_one_builtin_user(factory: StoreFactory) -> None:
    store = factory()
    with store() as uow:
        uow.users.add(make_user("one", builtin=True), None)
        with pytest.raises(ConflictError):
            uow.users.add(make_user("two", builtin=True), None)


ALL_CHECKS = [
    check_builtin_roles_exist,
    check_user_round_trip,
    check_duplicate_username_conflicts,
    check_role_removal_strips_users,
    check_sessions,
    check_security_version_round_trips,
    check_settings,
    check_nothing_persists_without_commit,
    check_only_if_empty,
    check_one_builtin_user,
]
