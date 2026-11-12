import threading

import pytest
from auth_helpers import make_world

from netview.application.usecases.auth.setup import SETUP_CODE_ALPHABET, SetupService, make_setup_code
from netview.domain.auth import ADMIN_ROLE
from netview.domain.errors import AuthenticationError, ConflictError, TooManyAttemptsError

PW = "correct horse battery"


def service(w, mode="enterprise", code="ABCD2345"):
    return SetupService(w.store, w.hasher, w.sessions, w.throttle, w.clock, mode, code, w.policy)


def test_status_open_until_first_user():
    w = make_world()
    s = service(w)
    assert s.status().open and s.status().code_required
    s.complete("ABCD2345", "Admin", PW, "ip", "ua")
    assert not s.status().open


def test_home_mode_needs_no_code():
    w = make_world()
    s = service(w, mode="home", code=None)
    assert not s.status().code_required
    result = s.complete(None, "admin", PW, "ip", "ua")
    assert result.principal.username == "admin"


def test_enterprise_wrong_code_rejected_and_throttled():
    w = make_world()
    s = service(w)
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            s.complete("WRONG123", "admin", PW, "ip", "ua")
    with pytest.raises(TooManyAttemptsError):
        s.complete("ABCD2345", "admin", PW, "ip", "ua")
    assert s.status().open


def test_missing_code_rejected():
    w = make_world()
    with pytest.raises(AuthenticationError):
        service(w).complete(None, "admin", PW, "ip", "ua")


def test_code_is_case_insensitive():
    w = make_world()
    assert service(w).complete("abcd2345", "admin", PW, "ip", "ua").token


def test_complete_creates_builtin_admin_and_signs_in():
    w = make_world()
    result = service(w).complete("ABCD2345", " Admin ", PW, "ip", "ua")
    assert result.principal.can("core.system")
    with w.store() as uow:
        user = uow.users.by_username("admin")
    assert user is not None
    assert user.builtin and user.role_ids == {ADMIN_ROLE} and user.provider == "local"
    assert w.sessions.resolve(result.token) is not None
    assert w.sign_in("admin", PW, "ip", "ua").principal.user_id == user.id


def test_second_complete_conflicts():
    w = make_world()
    s = service(w)
    s.complete("ABCD2345", "admin", PW, "ip", "ua")
    with pytest.raises(ConflictError):
        s.complete("ABCD2345", "other", PW, "ip", "ua")


def test_racing_completes_create_one_admin():
    w = make_world()
    s = service(w, mode="home", code=None)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def go(name: str) -> None:
        barrier.wait()
        try:
            s.complete(None, name, PW, "ip", "ua")
            outcomes.append("ok")
        except ConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=go, args=(n,)) for n in ("admin1", "admin2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict", "ok"]
    with w.store() as uow:
        assert uow.users.count() == 1


def test_make_setup_code_alphabet():
    for _ in range(1000):
        code = make_setup_code()
        assert len(code) == 8
        assert set(code) <= set(SETUP_CODE_ALPHABET)


def test_parallel_wrong_codes_are_capped_at_the_lockout_limit():
    w = make_world()
    s = service(w)
    barrier = threading.Barrier(20)
    outcomes = []

    def guess(i):
        barrier.wait()
        try:
            s.complete(f"WRONG{i:03d}", "admin", PW, "ip", "ua")
        except (AuthenticationError, TooManyAttemptsError) as exc:
            outcomes.append(type(exc))

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count(AuthenticationError) <= 5
    assert outcomes.count(TooManyAttemptsError) >= 15
