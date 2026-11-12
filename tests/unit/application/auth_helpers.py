"""Shared builders for the auth use case tests."""

from collections.abc import Callable
from dataclasses import dataclass

from netview.application.usecases.auth.sessions import Authorizer, SessionService
from netview.application.usecases.auth.sign_in import LoginThrottle, SignIn
from netview.domain.auth import DEFAULT_ROLE, AuthPolicy, User
from netview.infrastructure.auth.memory_store import InMemoryAuthStore
from netview.sdk.testing.fakes import FakeClock


class PlainHasher:
    def hash(self, password: str) -> str:
        return "h:" + password

    def verify(self, hash: str, password: str) -> bool:
        return hash == "h:" + password

    def needs_rehash(self, hash: str) -> bool:
        return False


def make_user(
    username: str = "kdoe", roles: frozenset[str] = frozenset({DEFAULT_ROLE}), **kw: object
) -> User:
    fields: dict[str, object] = {
        "id": 0,
        "username": username,
        "display_name": username,
        "email": None,
        "enabled": True,
        "builtin": False,
        "must_change_password": False,
        "role_ids": roles,
        "provider": "local",
        "created_ms": 0,
        "last_sign_in_ms": None,
    }
    fields.update(kw)
    return User(**fields)  # type: ignore[arg-type]


@dataclass
class AuthWorld:
    store: InMemoryAuthStore
    clock: FakeClock
    hasher: PlainHasher
    authorizer: Authorizer
    policy: Callable[[], AuthPolicy]
    sessions: SessionService
    throttle: LoginThrottle
    sign_in: SignIn

    def add_user(self, username: str = "kdoe", password: str = "correct horse battery", **kw: object) -> User:
        with self.store() as uow:
            user = uow.users.add(make_user(username, **kw), self.hasher.hash(password))  # type: ignore[arg-type]
            uow.commit()
        return user


def make_world() -> AuthWorld:
    store = InMemoryAuthStore()
    clock = FakeClock()
    hasher = PlainHasher()
    authorizer = Authorizer(store)

    def policy() -> AuthPolicy:
        return AuthPolicy()

    sessions = SessionService(store, clock, authorizer, policy)
    throttle = LoginThrottle(clock, policy)
    return AuthWorld(
        store,
        clock,
        hasher,
        authorizer,
        policy,
        sessions,
        throttle,
        SignIn(store, hasher, sessions, throttle, clock),
    )
