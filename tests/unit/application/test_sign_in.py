import contextlib
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
    change = ChangeOwnPassword(w.store, w.hasher, w.sessions, w.throttle, w.policy, w.clock)
    change(first.principal, GOOD, "a brand new passphrase", first.token, "10.0.0.2")
    assert w.sessions.resolve(second.token) is None
    kept = w.sessions.resolve(first.token)
    assert kept is not None and not kept.must_change_password
    assert attempt(w, password="a brand new passphrase").principal.user_id == user.id


def test_change_password_checks_current_and_policy():
    w = make_world()
    w.add_user()
    result = attempt(w)
    change = ChangeOwnPassword(w.store, w.hasher, w.sessions, w.throttle, w.policy, w.clock)
    with pytest.raises(AuthenticationError):
        change(result.principal, "wrong", "a brand new passphrase", result.token, "10.0.0.2")
    with pytest.raises(ValidationError):
        change(result.principal, GOOD, "short", result.token, "10.0.0.2")


def test_parallel_wrong_guesses_are_capped_at_the_lockout_limit():
    import threading
    import time

    from auth_helpers import PlainHasher

    from netview.application.usecases.auth.sign_in import SignIn

    w = make_world()
    w.add_user()
    verifies = []

    class SlowHasher(PlainHasher):
        def verify(self, hash, password):
            verifies.append(password)
            time.sleep(0.05)
            return super().verify(hash, password)

    sign_in = SignIn(w.store, SlowHasher(), w.sessions, w.throttle, w.clock)
    barrier = threading.Barrier(20)
    outcomes = []

    def guess(i):
        barrier.wait()
        try:
            sign_in("kdoe", f"wrong{i}", "10.0.0.2", "ua")
        except (AuthenticationError, TooManyAttemptsError) as exc:
            outcomes.append(type(exc))

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(verifies) <= 5
    assert len(outcomes) == 20


def test_throttle_release_frees_a_reserved_attempt():
    w = make_world()
    for _ in range(5):
        w.throttle.begin("kdoe", "ip")
    with pytest.raises(TooManyAttemptsError):
        w.throttle.begin("kdoe", "ip")
    w.throttle.release("kdoe", "ip")
    w.throttle.begin("kdoe", "ip")


def _tracked(throttle):
    return len(throttle._failures) + len(throttle._locked_until) + len(throttle._pending)


def test_throttle_memory_is_bounded_for_unique_and_long_usernames():
    w = make_world()
    long_name = "x" * 100_000
    w.throttle.begin(long_name, "ip")
    w.throttle.failed(long_name, "ip")
    assert all(len(name) <= 64 for name, _ in w.throttle._failures)
    for i in range(50):  # one address per name: a single address is locked after 20 (per-address limit)
        w.throttle.begin(f"\u0430{i}", f"10.4.0.{i}")
        w.throttle.failed(f"\u0430{i}", f"10.4.0.{i}")
    assert _tracked(w.throttle) >= 51
    w.clock.advance(901_000)
    w.throttle.begin("kdoe", "ip")
    w.throttle.release("kdoe", "ip")
    assert _tracked(w.throttle) == 0


def _fail(throttle, username, ip):
    throttle.begin(username, ip)
    throttle.failed(username, ip)


def test_full_table_frees_unlocked_entries_before_refusing():
    from netview.application.usecases.auth.sign_in import LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy, max_keys=20)
    for i in range(100):  # one failure each from many addresses: nothing is locked, so nobody is refused
        w.clock.advance(1)
        _fail(throttle, f"user{i}", f"10.1.0.{i}")
    assert _tracked(throttle) <= 20
    throttle.begin("kdoe", "10.0.0.5")  # a real user still gets in line


def test_ipv6_addresses_count_per_64_block():
    w = make_world()
    for i in range(20):  # one host rotating through its /64
        _fail(w.throttle, f"guess{i}", f"2001:db8:1:2::{i + 1:x}")
    with pytest.raises(TooManyAttemptsError):
        w.throttle.begin("kdoe", "2001:db8:1:2::ffff")
    w.throttle.begin("kdoe", "2001:db8:1:3::1")  # a different /64 is unaffected


def test_a_table_full_of_junk_lockouts_never_allows_unlimited_guessing():
    from netview.application.usecases.auth.sign_in import LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy, max_keys=20)
    for i in range(40):  # fill the table with locked junk keys from many sources
        for _ in range(5):
            w.clock.advance(1)
            try:
                _fail(throttle, f"filler{i}", f"10.2.0.{i}")
            except TooManyAttemptsError:
                break
    allowed = 0
    for _ in range(50):  # then guess the real account from a fresh address
        try:
            _fail(throttle, "kdoe", "10.9.9.9")
            allowed += 1
        except TooManyAttemptsError:
            pass
    assert allowed <= 5


def test_flooding_other_keys_never_unlocks_a_locked_one():
    from netview.application.usecases.auth.sign_in import LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy, max_keys=20)
    for _ in range(5):
        _fail(throttle, "kdoe", "10.0.0.66")
    for i in range(200):
        w.clock.advance(1)
        with contextlib.suppress(TooManyAttemptsError):
            _fail(throttle, f"filler{i}", f"10.3.{i // 250}.{i % 250}")
    with pytest.raises(TooManyAttemptsError):
        throttle.begin("kdoe", "10.0.0.66")


def test_one_address_is_locked_after_failures_across_many_usernames():
    w = make_world()
    w.add_user("kdoe")
    for i in range(20):  # 4 x lockout_failures, spread over usernames so no single key locks
        _fail(w.throttle, f"guess{i}", "10.0.0.9")
    with pytest.raises(TooManyAttemptsError):
        attempt(w, username="kdoe", ip="10.0.0.9")
    assert attempt(w, username="kdoe", ip="10.0.0.10").principal.username == "kdoe"
    w.clock.advance(901_000)
    assert attempt(w, username="kdoe", ip="10.0.0.9").principal.username == "kdoe"


def test_parallel_guesses_across_usernames_respect_the_address_limit():
    import threading

    w = make_world()
    allowed = 0
    lock = threading.Lock()
    barrier = threading.Barrier(40)

    def go(i):
        nonlocal allowed
        barrier.wait()
        try:
            w.throttle.begin(f"guess{i}", "10.0.0.7")
        except TooManyAttemptsError:
            return
        with lock:
            allowed += 1

    threads = [threading.Thread(target=go, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert allowed == 20


def test_change_password_wrong_current_is_throttled():
    w = make_world()
    w.add_user()
    result = attempt(w)
    change = ChangeOwnPassword(w.store, w.hasher, w.sessions, w.throttle, w.policy, w.clock)
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            change(result.principal, "wrong", "a brand new passphrase", result.token, "10.0.0.2")
    with pytest.raises(TooManyAttemptsError):
        change(result.principal, "wrong", "a brand new passphrase", result.token, "10.0.0.2")
    with pytest.raises(TooManyAttemptsError):
        change(result.principal, GOOD, "a brand new passphrase", result.token, "10.0.0.2")


def test_change_password_policy_failure_does_not_count_as_a_guess():
    w = make_world()
    w.add_user()
    result = attempt(w)
    change = ChangeOwnPassword(w.store, w.hasher, w.sessions, w.throttle, w.policy, w.clock)
    for _ in range(10):
        with pytest.raises(ValidationError):
            change(result.principal, GOOD, "short", result.token, "10.0.0.2")
    change(result.principal, GOOD, "a brand new passphrase", result.token, "10.0.0.2")
