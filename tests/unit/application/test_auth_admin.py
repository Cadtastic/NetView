import pytest
from auth_helpers import AuthWorld, make_world

from netview.application.auth.catalog import build_catalog
from netview.application.usecases.auth.admin import PolicyAdmin, RoleAdmin, UserAdmin
from netview.domain.auth import ADMIN_ROLE, DEFAULT_ROLE, Role
from netview.domain.errors import ConflictError, ValidationError

PW = "correct horse battery"


def admins(w: AuthWorld):
    users = UserAdmin(w.store, w.hasher, w.sessions, w.authorizer, w.policy, w.clock)
    roles = RoleAdmin(w.store, w.authorizer, lambda: build_catalog([]))
    return users, roles


def add_builtin(w: AuthWorld):
    return w.add_user("admin", builtin=True, roles=frozenset({ADMIN_ROLE}))


def test_builtin_admin_cannot_be_disabled_deleted_or_demoted():
    w = make_world()
    users, _ = admins(w)
    admin = add_builtin(w)
    with pytest.raises(ValidationError):
        users.update(admin.id, enabled=False)
    with pytest.raises(ValidationError):
        users.update(admin.id, role_ids={DEFAULT_ROLE})
    with pytest.raises(ValidationError):
        users.delete(admin.id)
    assert users.update(admin.id, display_name="Boss").display_name == "Boss"


def test_default_role_editable_not_deletable():
    w = make_world()
    _, roles = admins(w)
    updated = roles.update(DEFAULT_ROLE, permissions={"core.view", "core.rename"})
    assert updated.permissions == {"core.view", "core.rename"}
    with pytest.raises(ValidationError):
        roles.delete(DEFAULT_ROLE)
    with pytest.raises(ValidationError):
        roles.update(DEFAULT_ROLE, name="Everyone")


def test_administrator_permissions_not_editable():
    w = make_world()
    _, roles = admins(w)
    with pytest.raises(ValidationError):
        roles.update(ADMIN_ROLE, permissions={"core.view"})
    with pytest.raises(ValidationError):
        roles.delete(ADMIN_ROLE)


def test_cannot_grant_install():
    w = make_world()
    _, roles = admins(w)
    with pytest.raises(ValidationError):
        roles.update(DEFAULT_ROLE, permissions={"core.view", "core.install"})


def test_stale_permission_kept_new_unknown_rejected():
    w = make_world()
    _, roles = admins(w)
    with w.store() as uow:
        uow.roles.add(Role("helpdesk", "Helpdesk", False, frozenset({"core.view", "gone.use"})))
        uow.commit()
    kept = roles.update("helpdesk", permissions={"core.view", "core.scan"})
    assert kept.permissions == {"core.view", "core.scan", "gone.use"}
    with pytest.raises(ValidationError):
        roles.update("helpdesk", permissions={"core.view", "other.use"})
    same = roles.update("helpdesk", permissions={"core.view", "gone.use"})
    assert "gone.use" in same.permissions


def test_disable_ends_sessions():
    w = make_world()
    users, _ = admins(w)
    user = w.add_user()
    token = w.sign_in("kdoe", PW, "ip", "ua").token
    assert w.sessions.resolve(token) is not None
    users.update(user.id, enabled=False)
    assert w.sessions.resolve(token) is None


def test_delete_and_reset_password_end_sessions():
    w = make_world()
    users, _ = admins(w)
    a = w.add_user("a")
    b = w.add_user("b")
    ta = w.sign_in("a", PW, "ip", "ua").token
    tb = w.sign_in("b", PW, "ip", "ua").token
    users.reset_password(a.id, "another long passphrase")
    assert w.sessions.resolve(ta) is None
    with w.store() as uow:
        refreshed = uow.users.get(a.id)
    assert refreshed is not None and refreshed.must_change_password
    users.delete(b.id)
    assert w.sessions.resolve(tb) is None


def test_role_change_invalidates_authorizer():
    w = make_world()
    users, roles = admins(w)
    user = w.add_user()
    token = w.sessions.create(user.id, "ip", "ua")
    before = w.sessions.resolve(token)
    assert before is not None and not before.can("core.rename")
    roles.update(DEFAULT_ROLE, permissions={"core.view", "core.rename"})
    after = w.sessions.resolve(token)
    assert after is not None and after.can("core.rename")
    helpdesk = roles.create("Help Desk")
    users.update(user.id, role_ids={DEFAULT_ROLE, helpdesk.id})
    roles.update(helpdesk.id, permissions={"core.scan"})
    again = w.sessions.resolve(token)
    assert again is not None and again.can("core.scan")


def test_unknown_role_rejected():
    w = make_world()
    users, _ = admins(w)
    user = w.add_user()
    with pytest.raises(ValidationError):
        users.update(user.id, role_ids={"nope"})
    with pytest.raises(ValidationError):
        users.create_local("new", "New", PW, {"nope"})


def test_create_local_requires_policy_and_marks_must_change():
    w = make_world()
    users, _ = admins(w)
    with pytest.raises(ValidationError):
        users.create_local("new", "New", "short", {DEFAULT_ROLE})
    with pytest.raises(ValidationError):
        users.create_local("новый user", "New", PW, {DEFAULT_ROLE})
    created = users.create_local(" New.User ", "New User", PW, {DEFAULT_ROLE})
    assert created.username == "new.user" and created.must_change_password and not created.builtin
    with pytest.raises(ConflictError):
        users.create_local("NEW.USER", "Again", PW, {DEFAULT_ROLE})
    assert w.sign_in("new.user", PW, "ip", "ua").principal.must_change_password


def test_policy_update_persists_and_validates_floor():
    w = make_world()
    policy = PolicyAdmin(w.store)
    assert policy.get().password_min_length == 12
    updated = policy.update(password_min_length=10, session_idle_s=600)
    assert updated.password_min_length == 10
    reread = PolicyAdmin(w.store).get()
    assert reread.password_min_length == 10 and reread.session_idle_s == 600
    assert reread.lockout_failures == 5
    with pytest.raises(ValidationError):
        policy.update(password_min_length=7)
    with pytest.raises(ValidationError):
        policy.update(nonsense=1)
    assert policy.get().password_min_length == 10


def test_role_create_slug_and_clash():
    w = make_world()
    _, roles = admins(w)
    role = roles.create("  Help Desk! ")
    assert role.id == "help-desk" and role.name == "Help Desk!" and not role.builtin
    with pytest.raises(ConflictError):
        roles.create("help desk")
    with pytest.raises(ValidationError):
        roles.create("!!!")


def test_role_delete_removes_from_users_and_list_counts():
    w = make_world()
    users, roles = admins(w)
    helpdesk = roles.create("Helpdesk")
    user = w.add_user()
    users.update(user.id, role_ids={DEFAULT_ROLE, helpdesk.id})
    counts = {v.role.id: v.user_count for v in roles.list()}
    assert counts[helpdesk.id] == 1 and counts[DEFAULT_ROLE] == 1 and counts[ADMIN_ROLE] == 0
    roles.delete(helpdesk.id)
    with w.store() as uow:
        stored = uow.users.get(user.id)
    assert stored is not None and stored.role_ids == {DEFAULT_ROLE}
