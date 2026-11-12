from dataclasses import replace

from auth_helpers import make_world

from netview.application.usecases.auth.sessions import hash_token
from netview.domain.auth import ADMIN_ROLE


def test_resolve_returns_principal_with_role_permissions():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "10.0.0.2", "ua")
    principal = w.sessions.resolve(token)
    assert principal is not None
    assert principal.username == "kdoe"
    assert principal.can("core.view")
    assert not principal.can("core.rename")


def test_administrator_has_everything():
    w = make_world()
    user = w.add_user("root", roles=frozenset({ADMIN_ROLE}))
    principal = w.sessions.resolve(w.sessions.create(user.id, "ip", "ua"))
    assert principal is not None and principal.can("anything.at.all")


def test_unknown_token_resolves_none():
    assert make_world().sessions.resolve("nope") is None


def test_idle_timeout_expires_session():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    w.clock.advance(28_801_000)
    assert w.sessions.resolve(token) is None
    with w.store() as uow:
        assert uow.sessions.get(hash_token(token)) is None


def test_activity_keeps_session_alive_inside_idle_limit():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    w.clock.advance(28_000_000)
    assert w.sessions.resolve(token) is not None
    w.clock.advance(28_000_000)
    assert w.sessions.resolve(token) is not None


def test_absolute_lifetime_expires_even_when_active():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    for _ in range(7 * 24):
        w.clock.advance(3_600_000)
        assert w.sessions.resolve(token) is not None
    w.clock.advance(1_000)
    assert w.sessions.resolve(token) is None


def test_disabled_user_session_resolves_none():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    assert w.sessions.resolve(token) is not None
    with w.store() as uow:
        uow.users.save(replace(user, enabled=False))
        uow.commit()
    assert w.sessions.resolve(token) is None


def test_deleted_user_session_resolves_none():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    with w.store() as uow:
        uow.users.remove(user.id)
        uow.commit()
    assert w.sessions.resolve(token) is None


def test_role_edit_visible_after_invalidate():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    first = w.sessions.resolve(token)
    assert first is not None and not first.can("core.rename")
    with w.store() as uow:
        role = uow.roles.get("default")
        assert role is not None
        uow.roles.save(replace(role, permissions=role.permissions | {"core.rename"}))
        uow.commit()
    stale = w.sessions.resolve(token)
    assert stale is not None and not stale.can("core.rename")
    w.authorizer.invalidate()
    fresh = w.sessions.resolve(token)
    assert fresh is not None and fresh.can("core.rename")


def test_token_stored_hashed():
    w = make_world()
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    with w.store() as uow:
        assert uow.sessions.get(token) is None
        record = uow.sessions.get(hash_token(token))
    assert record is not None and record.token_hash != token
    assert len(record.token_hash) == 64


def test_end_and_end_all():
    w = make_world()
    user = w.add_user()
    a = w.sessions.create(user.id, "ip", "ua")
    b = w.sessions.create(user.id, "ip", "ua")
    w.sessions.end(a)
    assert w.sessions.resolve(a) is None
    assert w.sessions.resolve(b) is not None
    w.sessions.end_all(user.id)
    assert w.sessions.resolve(b) is None


def test_invalidate_between_load_and_store_is_not_overwritten(monkeypatch):
    from netview.application.usecases.auth import sessions as sessions_module
    from netview.domain.auth import DEFAULT_ROLE

    w = make_world()
    user = w.add_user()
    real = sessions_module.resolve_permissions
    calls = []

    def racing(roles):
        resolved = real(roles)  # the stale answer, computed before the role change below
        if not calls:
            calls.append(1)
            with w.store() as uow:
                role = uow.roles.get(DEFAULT_ROLE)
                uow.roles.save(replace(role, permissions=role.permissions | {"core.rename"}))
                uow.commit()
            w.authorizer.invalidate()
        return resolved

    monkeypatch.setattr(sessions_module, "resolve_permissions", racing)
    assert not w.authorizer.permissions(user).has("core.rename")  # the racing call itself may be stale
    assert w.authorizer.permissions(user).has("core.rename")  # but the stale value was not cached
