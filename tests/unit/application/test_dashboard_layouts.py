import pytest
from auth_helpers import AuthWorld, make_world

from netview.application.auth.principal import SYSTEM_PRINCIPAL, Principal
from netview.application.usecases.dashboard import DEFAULT_KEY, DashboardLayouts
from netview.domain.auth import PermissionSet, Role
from netview.domain.dashboard import DashboardLayout
from netview.domain.errors import NotFoundError, ValidationError

TILE = "core.tile.devices"
CARD = "core.card.traffic"


def layout(*order: str, group: str = "none") -> DashboardLayout:
    return DashboardLayout(tuple(order), (), (), group)


def principal(user_id: int | None, *permissions: str) -> Principal:
    return Principal(
        user_id=user_id,
        username="u",
        display_name="u",
        provider="local",
        permissions=PermissionSet(everything=False, ids=frozenset(permissions)),
    )


def setup() -> tuple[AuthWorld, DashboardLayouts]:
    w = make_world()
    w.clock.advance(5)
    return w, DashboardLayouts(w.store, w.clock)


def customizer(w: AuthWorld, name: str) -> Principal:
    user = w.add_user(name)
    return principal(user.id, "core.view", "core.dashboard")


def test_mine_prefers_own_then_default_then_builtin():
    w, svc = setup()
    me = customizer(w, "a")
    view = svc.mine(me)
    assert (view.source, view.layout, view.default, view.updated_ms) == ("builtin", None, None, None)

    svc.save_default(SYSTEM_PRINCIPAL, layout(TILE), clear_mine=False)
    view = svc.mine(me)
    assert view.source == "default"
    assert view.layout == layout(TILE) == view.default

    saved = svc.save_mine(me, layout(CARD))
    assert saved.source == "user"
    assert saved.layout == layout(CARD)
    assert saved.updated_ms == w.clock.now_ms()
    assert saved.default == layout(TILE)
    assert svc.mine(me).source == "user"


def test_own_layout_is_ignored_without_core_dashboard():
    w, svc = setup()
    me = customizer(w, "a")
    svc.save_mine(me, layout(CARD))
    viewer = principal(me.user_id, "core.view")
    assert svc.mine(viewer).source == "builtin"
    svc.save_default(SYSTEM_PRINCIPAL, layout(TILE), clear_mine=False)
    assert svc.mine(viewer).source == "default"


def test_reset_mine_deletes_and_returns_what_applies_now():
    w, svc = setup()
    me = customizer(w, "a")
    svc.save_default(SYSTEM_PRINCIPAL, layout(TILE), clear_mine=False)
    svc.save_mine(me, layout(CARD))
    view = svc.reset_mine(me)
    assert view.source == "default"
    assert svc.reset_mine(me).source == "default"  # idempotent
    assert svc.default().users_with_own_layout == 0


def test_save_default_with_clear_mine_removes_only_the_actors_layout():
    w, svc = setup()
    admin = customizer(w, "admin1")
    other = customizer(w, "b")
    svc.save_mine(admin, layout(CARD))
    svc.save_mine(other, layout(CARD))
    view = svc.save_default(admin, layout(TILE), clear_mine=True)
    assert view.users_with_own_layout == 1
    assert svc.mine(admin).source == "default"
    assert svc.mine(other).source == "user"


def test_reset_everyone_returns_the_count():
    w, svc = setup()
    svc.save_mine(customizer(w, "a"), layout(CARD))
    svc.save_mine(customizer(w, "b"), layout(CARD))
    assert svc.reset_everyone() == 2
    assert svc.reset_everyone() == 0


def test_corrupt_or_old_records_fall_back():
    w, svc = setup()
    me = customizer(w, "a")
    with w.store() as uow:
        uow.settings.set(DEFAULT_KEY, "{not json")
        uow.commit()
    view = svc.mine(me)
    assert (view.source, view.layout, view.default) == ("builtin", None, None)
    svc.save_default(SYSTEM_PRINCIPAL, layout(TILE), clear_mine=False)
    with w.store() as uow:
        uow.layouts.put(me.user_id, '{"version": 7}', 1)
        uow.commit()
    view = svc.mine(me)
    assert view.source == "default"
    assert view.layout == layout(TILE)
    with w.store() as uow:
        uow.layouts.put(me.user_id, "[1,", 1)
        uow.commit()
    assert svc.mine(me).source == "default"


def test_roles_with_permission_lists_names_and_always_administrator():
    w, svc = setup()
    with w.store() as uow:
        uow.roles.add(Role("zeta", "Zeta", False, frozenset({"core.dashboard"})))
        uow.roles.add(Role("alpha", "Alpha", False, frozenset({"core.dashboard", "core.view"})))
        uow.roles.add(Role("other", "Other", False, frozenset({"core.view"})))
        uow.commit()
    names = svc.default().roles_with_permission
    assert names == sorted(names)
    assert {"Alpha", "Zeta", "Administrator"} <= set(names)
    assert "Other" not in names


def test_system_principal_cannot_save():
    _, svc = setup()
    with pytest.raises(ValidationError):
        svc.save_mine(SYSTEM_PRINCIPAL, layout(TILE))
    with pytest.raises(ValidationError):
        svc.reset_mine(SYSTEM_PRINCIPAL)


def test_save_mine_for_a_deleted_account_is_not_found():
    _, svc = setup()
    with pytest.raises(NotFoundError):
        svc.save_mine(principal(4242, "core.dashboard"), layout(TILE))
