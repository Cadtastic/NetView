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
    held = [w.throttle.begin("kdoe", "ip") for _ in range(5)]
    with pytest.raises(TooManyAttemptsError):
        w.throttle.begin("kdoe", "ip")
    w.throttle.release(held[0])
    w.throttle.begin("kdoe", "ip")


def _tracked(throttle):
    return len(throttle._failures) + len(throttle._locked_until) + len(throttle._pending)


def test_throttle_memory_is_bounded_for_unique_and_long_usernames():
    w = make_world()
    long_name = "x" * 100_000
    w.throttle.failed(w.throttle.begin(long_name, "ip"))
    assert all(len(name) <= 64 for name, _ in w.throttle._failures)
    for i in range(50):  # one address per name: a single address is locked after 20 (per-address limit)
        w.throttle.failed(w.throttle.begin(f"\u0430{i}", f"10.4.0.{i}"))
    assert _tracked(w.throttle) >= 51
    w.clock.advance(901_000)
    w.throttle.release(w.throttle.begin("kdoe", "ip"))
    assert _tracked(w.throttle) == 0


def _fail(throttle, username, ip):
    throttle.failed(throttle.begin(username, ip))


def test_full_table_frees_username_counts_before_refusing():
    from netview.application.usecases.auth.sign_in import LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy, max_keys=20)
    for i in range(75):  # 5 addresses x 15 usernames: lots of username counts, no address at its cap
        w.clock.advance(1)
        _fail(throttle, f"user{i}", f"10.1.0.{i % 5}")
    assert _tracked(throttle) <= 20
    throttle.begin("kdoe", "10.0.0.5")  # a real user from a new address still gets in line


def test_ipv6_addresses_are_counted_exactly_because_a_lan_shares_one_64():
    w = make_world()
    for i in range(20):  # a bad actor on the LAN locks only their own address, not every IPv6 neighbour
        _fail(w.throttle, f"guess{i}", "2001:db8:1:2::66")
    with pytest.raises(TooManyAttemptsError):
        w.throttle.begin("kdoe", "2001:db8:1:2::66")
    w.throttle.begin("kdoe", "2001:db8:1:2::77")


def test_ipv4_mapped_ipv6_counts_as_the_ipv4_address():
    w = make_world()
    for i in range(20):
        _fail(w.throttle, f"guess{i}", "::ffff:10.0.0.8")
    with pytest.raises(TooManyAttemptsError):
        w.throttle.begin("kdoe", "10.0.0.8")


def test_address_counts_are_never_freed_while_inside_the_window():
    from netview.application.usecases.auth.sign_in import LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy, max_keys=30)
    for i in range(19):  # one address, 19 failures across usernames: one short of its lock
        _fail(throttle, f"guess{i}", "10.0.0.99")
    for i in range(60):  # pressure from other sources
        w.clock.advance(1)
        with contextlib.suppress(TooManyAttemptsError):
            _fail(throttle, f"other{i}", f"10.5.0.{i}")
    _fail(throttle, "guess19", "10.0.0.99")  # the 20th failure still counts...
    with pytest.raises(TooManyAttemptsError):  # ...so the address is locked
        throttle.begin("kdoe", "10.0.0.99")


def test_a_full_table_never_allows_more_than_the_limit():
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


# ---- tiered limits: per username+address, per address, and per IPv6 /64 ----


def _count_allowed(throttle, attempts):
    allowed = 0
    for username, ip in attempts:
        try:
            _fail(throttle, username, ip)
            allowed += 1
        except TooManyAttemptsError:
            pass
    return allowed


def test_rotating_through_a_64_against_one_account_is_capped_at_20():
    w = make_world()
    tries = [("kdoe", f"2001:db8:1:2::{i + 1:x}") for i in range(300)]  # a fresh address for every guess
    assert _count_allowed(w.throttle, tries) == 20  # username + /64 tier: 4 x lockout_failures


def test_spraying_usernames_from_a_64_is_capped_by_the_backstop():
    w = make_world()
    tries = [(f"user{i}", f"2001:db8:1:2::{i + 1:x}") for i in range(600)]
    assert _count_allowed(w.throttle, tries) == 250  # whole-/64 backstop: 50 x lockout_failures


def test_five_noisy_addresses_do_not_lock_their_ipv6_neighbours():
    w = make_world()
    for a in range(5):  # one host, five privacy addresses, 20 failures each (100 in all)
        for i in range(20):
            with contextlib.suppress(TooManyAttemptsError):
                _fail(w.throttle, f"guess{a}-{i}", f"2001:db8:1:2::{a + 1:x}")
    w.throttle.begin("kdoe", "2001:db8:1:2::abcd")  # a neighbour on the same /64 still gets in line


def test_settling_uses_exactly_what_begin_reserved():
    w = make_world()
    for i in range(8):  # fill the /64's exact-address slots
        _fail(w.throttle, f"u{i}", f"2001:db8:5:5::{i + 1:x}")
    x = w.throttle.begin("kdoe", "2001:db8:5:5::99")  # over the cap: no exact-address count for ::99
    assert ("*", "2001:db8:5:5::99") not in x.keys
    w.clock.advance(901_000)  # the 8 counts expire, freeing a slot
    y = w.throttle.begin("kdoe", "2001:db8:5:5::99")  # this one does reserve ::99
    assert ("*", "2001:db8:5:5::99") in y.keys
    w.throttle.succeeded(x)
    w.throttle.failed(y)
    assert len(w.throttle._failures[("*", "2001:db8:5:5::99")]) == 1  # y's failure was recorded on ::99


def test_one_noisy_ipv6_address_does_not_lock_its_neighbours():
    w = make_world()
    for i in range(20):
        _fail(w.throttle, f"guess{i}", "2001:db8:1:2::66")
    with pytest.raises(TooManyAttemptsError):
        w.throttle.begin("kdoe", "2001:db8:1:2::66")
    w.throttle.begin("kdoe", "2001:db8:1:2::77")  # same /64, well under the prefix limit


def test_rotation_cannot_fill_the_table_with_address_counts():
    from netview.application.usecases.auth.sign_in import LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy, max_keys=200)
    for i in range(1000):
        w.clock.advance(1)
        with contextlib.suppress(TooManyAttemptsError):
            _fail(throttle, f"u{i}", f"2001:db8:9:9::{i + 1:x}")
    assert sum(1 for k in throttle._failures if k[0] == "*") <= 8
    throttle.begin("kdoe", "10.0.0.5")  # an IPv4 user elsewhere is unaffected


def test_prefix_bookkeeping_stays_small_under_rotation():
    from netview.application.usecases.auth.sign_in import MAX_ADDRESSES_PER_PREFIX, LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy)
    for i in range(500):
        w.clock.advance(1)
        with contextlib.suppress(TooManyAttemptsError):
            _fail(throttle, f"u{i}", f"2001:db8:7:7::{i + 1:x}")
    tracked = throttle._prefix_addresses.get("2001:db8:7:7::/64", set())
    assert len(tracked) <= MAX_ADDRESSES_PER_PREFIX
    w.clock.advance(901_000)
    throttle.release(throttle.begin("kdoe", "10.0.0.1"))
    throttle._sweep(w.clock.now_ms(), w.policy(), force=True)
    assert "2001:db8:7:7::/64" not in throttle._prefix_addresses  # emptied with the counts it tracked


def test_one_site_flooding_many_64s_does_not_fill_the_default_table():
    from netview.application.usecases.auth.sign_in import MAX_PREFIXES_PER_SITE, LoginThrottle

    w = make_world()
    throttle = LoginThrottle(w.clock, w.policy)  # default size
    for n in range(10_000):  # the review's attack: single failures spread over 160 /64s of one /48
        w.clock.advance(1)
        with contextlib.suppress(TooManyAttemptsError):
            _fail(throttle, "x", f"2001:db8:aa:{n % 160:x}::{n // 160 + 1:x}")
    assert len(throttle._site_prefixes.get("2001:db8:aa::/48", ())) <= MAX_PREFIXES_PER_SITE
    assert _tracked(throttle) < 1_000
    throttle.begin("admin", "192.168.1.10")  # everyone else still gets in line
