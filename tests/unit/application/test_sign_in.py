from dataclasses import replace

import pytest
from auth_helpers import make_world

from netview.application.usecases.auth.sign_in import ChangeOwnPassword
from netview.domain.errors import AuthenticationError, TooManyAttemptsError, ValidationError

GOOD = "correct horse battery"
GENERIC = "Username or password is wrong"


def attempt(w, username="kdoe", password=GOOD, ip="10.0.0.2"):
    return w.sign_in(username, password, ip, "ua")


def test_sign_in_returns_working_token():
    w = make_world()
    w.add_user()
    result = attempt(w)
    assert result.principal.username == "kdoe"
    assert w.sessions.resolve(result.token) is not None
    with w.store() as uow:
        user = uow.users.by_username("kdoe")
    assert user is not None and user.last_sign_in_ms == w.clock.now_ms()


def test_sign_in_wrong_password_generic_message():
    w = make_world()
    w.add_user()
    with pytest.raises(AuthenticationError, match=GENERIC):
        attempt(w, password="wrong")


def test_unknown_user_and_disabled_user_same_message():
    w = make_world()
    user = w.add_user()
    with pytest.raises(AuthenticationError, match=GENERIC):
        attempt(w, username="nobody")
    with w.store() as uow:
        uow.users.save(replace(user, enabled=False))
        uow.commit()
    with pytest.raises(AuthenticationError, match=GENERIC):
        attempt(w)


def test_non_local_user_cannot_sign_in_with_password():
    w = make_world()
    w.add_user(provider="ldap")
    with pytest.raises(AuthenticationError, match=GENERIC):
        attempt(w)


def test_invalid_username_is_generic_failure():
    w = make_world()
    with pytest.raises(AuthenticationError, match=GENERIC):
        attempt(w, username="\u0430dmin")


@pytest.mark.parametrize("typed", ["KDOE", " kdoe ", "\uff2b\uff24\uff2f\uff25"])
def test_sign_in_case_insensitive_username(typed):
    w = make_world()
    w.add_user("kdoe")
    assert attempt(w, username=typed).principal.username == "kdoe"


def test_lockout_after_five_failures_then_unlock_after_fifteen_minutes():
    w = make_world()
    w.add_user()
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            attempt(w, password="wrong")
    with pytest.raises(TooManyAttemptsError):
        attempt(w)
    w.clock.advance(900_000)
    assert attempt(w).principal.username == "kdoe"


def test_lockout_key_uses_normalized_username():
    w = make_world()
    w.add_user()
    for typed in ["KDOE", "kdoe", " Kdoe", "kdoe ", "KDoe"]:
        with pytest.raises(AuthenticationError):
            attempt(w, username=typed, password="wrong")
    with pytest.raises(TooManyAttemptsError):
        attempt(w, username="kDOE")


def test_lockout_is_per_ip():
    w = make_world()
    w.add_user()
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            attempt(w, password="wrong")
    assert attempt(w, ip="10.0.0.9").principal.username == "kdoe"


def test_failures_outside_window_do_not_count():
    w = make_world()
    w.add_user()
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            attempt(w, password="wrong")
    w.clock.advance(901_000)
    with pytest.raises(AuthenticationError):
        attempt(w, password="wrong")
    assert attempt(w).principal.username == "kdoe"


def test_success_resets_failures():
    w = make_world()
    w.add_user()
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            attempt(w, password="wrong")
    attempt(w)
    for _ in range(4):
        with pytest.raises(AuthenticationError):
            attempt(w, password="wrong")
    assert attempt(w).principal.username == "kdoe"


def test_change_password_clears_must_change_and_other_sessions():
    w = make_world()
    user = w.add_user(must_change_password=True)
    first = attempt(w)
    second = attempt(w)
    assert first.principal.must_change_password
    change = ChangeOwnPassword(w.store, w.hasher, w.sessions, w.policy, w.clock)
    change(first.principal, GOOD, "a brand new passphrase", first.token)
    assert w.sessions.resolve(second.token) is None
    kept = w.sessions.resolve(first.token)
    assert kept is not None and not kept.must_change_password
    assert attempt(w, password="a brand new passphrase").principal.user_id == user.id


def test_change_password_checks_current_and_policy():
    w = make_world()
    w.add_user()
    result = attempt(w)
    change = ChangeOwnPassword(w.store, w.hasher, w.sessions, w.policy, w.clock)
    with pytest.raises(AuthenticationError):
        change(result.principal, "wrong", "a brand new passphrase", result.token)
    with pytest.raises(ValidationError):
        change(result.principal, GOOD, "short", result.token)
