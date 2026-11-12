import pytest

from netview.domain.auth import (
    ADMIN_ROLE,
    AuthPolicy,
    Role,
    check_password,
    normalize_username,
    resolve_permissions,
)
from netview.domain.errors import ValidationError


def test_administrator_gets_everything():
    ps = resolve_permissions([Role(ADMIN_ROLE, "Administrator", True, frozenset())])
    assert ps.everything and ps.has("anything.at_all")


def test_permissions_add_up_across_roles():
    ps = resolve_permissions(
        [
            Role("a", "A", False, frozenset({"core.view"})),
            Role("b", "B", False, frozenset({"gsm7248.console"})),
        ]
    )
    assert ps.has("core.view") and ps.has("gsm7248.console") and not ps.has("core.users")


def test_no_roles_means_no_permissions():
    assert not resolve_permissions([]).has("core.view")


def test_as_list():
    assert resolve_permissions([Role(ADMIN_ROLE, "A", True, frozenset())]).as_list(["b", "a"]) == ["a", "b"]
    ps = resolve_permissions([Role("a", "A", False, frozenset({"x", "w"}))])
    assert ps.as_list(["x", "w", "z"]) == ["w", "x"]


@pytest.mark.parametrize(
    "raw",
    ["admin", " Admin ", "ADMIN", "\tadmin\n", "\uff21\uff24\uff2d\uff29\uff2e", "Admin ", "admin\u00a0"],
)
def test_usernames_normalize(raw):
    assert normalize_username(raw) == "admin"


@pytest.mark.parametrize("raw", ["", "   ", "ad min", "\u0430dmin", "adm\u0131n", "admin\u200b", "x" * 129])
def test_bad_usernames_rejected(raw):  # Cyrillic a, dotless i, zero-width space: look-alikes
    with pytest.raises(ValidationError):
        normalize_username(raw)


def test_email_usernames_allowed():
    assert normalize_username("KDoe+lab@Corp.com") == "kdoe+lab@corp.com"


def test_password_rules():
    check_password("correct horse battery", "admin", 12)
    for bad in ("short", "admin"):
        with pytest.raises(ValidationError):
            check_password(bad, "admin", 12)
    with pytest.raises(ValidationError):
        check_password("adminadminadmin", "adminadminadmin", 12)


def test_policy_defaults_and_floor():
    p = AuthPolicy()
    assert (p.password_min_length, p.session_idle_s, p.session_max_s) == (12, 28800, 604800)
    assert (p.lockout_failures, p.lockout_window_s, p.lockout_s) == (5, 900, 900)
    with pytest.raises(ValidationError) as e:
        AuthPolicy(password_min_length=7).validate()
    assert "password_min_length" in e.value.fields
