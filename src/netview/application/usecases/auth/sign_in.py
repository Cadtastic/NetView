"""Password sign-in, brute-force throttling and changing your own password."""

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

from netview.application.auth.principal import Principal
from netview.application.ports.auth_store import AuthStore
from netview.application.ports.clock import Clock
from netview.application.ports.password_hasher import PasswordHasher
from netview.application.usecases.auth.sessions import SessionService
from netview.domain.auth import AuthPolicy, check_password, normalize_username
from netview.domain.errors import AuthenticationError, NotFoundError, TooManyAttemptsError, ValidationError

WRONG_CREDENTIALS = "Username or password is wrong"


def _key(username: str, ip: str) -> tuple[str, str]:
    try:
        name = normalize_username(username)
    except ValidationError:
        # Unvalidated input: bound it so a stream of long, unique names cannot grow memory.
        name = "~" + hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()[:16]
    return (name, ip)


class LoginThrottle:
    """In-memory failure counter keyed by (normalized username, ip).

    ``begin`` reserves an attempt before the slow password check, so parallel requests cannot all
    pass the limit before any failure is recorded. Every ``begin`` must be settled by exactly one
    of ``failed``, ``succeeded`` or ``release``.
    """

    SWEEP_EVERY_MS = 60_000

    def __init__(self, clock: Clock, policy: Callable[[], AuthPolicy], max_keys: int = 10_000) -> None:
        self._clock = clock
        self._policy = policy
        self._max_keys = max_keys
        self._last_sweep = 0
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], list[int]] = {}
        self._locked_until: dict[tuple[str, str], int] = {}
        self._pending: dict[tuple[str, str], int] = {}

    def _sweep(self, now: int, policy: AuthPolicy) -> None:
        """Forget keys with no live failure, lock or reserved attempt; cap the total as a backstop."""
        if now - self._last_sweep < self.SWEEP_EVERY_MS and len(self._failures) <= self._max_keys:
            return
        self._last_sweep = now
        window = policy.lockout_window_s * 1000
        for key in [k for k, until in self._locked_until.items() if now >= until]:
            del self._locked_until[key]
            self._failures.pop(key, None)
        for key in [k for k, times in self._failures.items() if now - times[-1] > window]:
            if key not in self._locked_until:
                del self._failures[key]
        excess = len(self._failures) - self._max_keys
        if excess > 0:
            # Oldest first, unlocked before locked.
            order = sorted(self._failures, key=lambda k: (k in self._locked_until, self._failures[k][-1]))
            for key in order[:excess]:
                del self._failures[key]
                self._locked_until.pop(key, None)

    def begin(self, username: str, ip: str) -> None:
        key = _key(username, ip)
        now = self._clock.now_ms()
        policy = self._policy()
        with self._lock:
            self._sweep(now, policy)
            until = self._locked_until.get(key)
            if until is not None:
                if now < until:
                    raise TooManyAttemptsError()
                del self._locked_until[key]
                self._failures.pop(key, None)
            recent = [t for t in self._failures.get(key, []) if now - t <= policy.lockout_window_s * 1000]
            pending = self._pending.get(key, 0)
            if len(recent) + pending >= policy.lockout_failures:
                raise TooManyAttemptsError()
            self._pending[key] = pending + 1

    def _settle(self, key: tuple[str, str]) -> None:
        left = self._pending.get(key, 0) - 1
        if left > 0:
            self._pending[key] = left
        else:
            self._pending.pop(key, None)

    def release(self, username: str, ip: str) -> None:
        """Settle a ``begin`` that ended in neither a failure nor a success."""
        with self._lock:
            self._settle(_key(username, ip))

    def failed(self, username: str, ip: str) -> None:
        key = _key(username, ip)
        now = self._clock.now_ms()
        policy = self._policy()
        with self._lock:
            self._settle(key)
            recent = [t for t in self._failures.get(key, []) if now - t <= policy.lockout_window_s * 1000]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= policy.lockout_failures:
                self._locked_until[key] = now + policy.lockout_s * 1000
            self._sweep(now, policy)

    def succeeded(self, username: str, ip: str) -> None:
        key = _key(username, ip)
        with self._lock:
            self._settle(key)
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


@dataclass(frozen=True)
class SignInResult:
    token: str
    principal: Principal


class SignIn:
    def __init__(
        self,
        store: AuthStore,
        hasher: PasswordHasher,
        sessions: SessionService,
        throttle: LoginThrottle,
        clock: Clock,
    ) -> None:
        self._store = store
        self._hasher = hasher
        self._sessions = sessions
        self._throttle = throttle
        self._clock = clock
        self._dummy: str | None = None

    def _dummy_hash(self) -> str:
        if self._dummy is None:
            self._dummy = self._hasher.hash("netview-dummy-password")
        return self._dummy

    def __call__(self, username: str, password: str, ip: str, user_agent: str) -> SignInResult:
        self._throttle.begin(username, ip)
        try:
            return self._sign_in(username, password, ip, user_agent)
        except AuthenticationError:
            raise
        except BaseException:
            self._throttle.release(username, ip)
            raise

    def _sign_in(self, username: str, password: str, ip: str, user_agent: str) -> SignInResult:
        try:
            name = normalize_username(username)
        except ValidationError:
            self._hasher.verify(self._dummy_hash(), password)
            self._throttle.failed(username, ip)
            raise AuthenticationError(WRONG_CREDENTIALS) from None
        # Argon2 is slow and SQLite has one writer: never hash while a unit of work is open.
        with self._store() as uow:
            user = uow.users.by_username(name)
            stored = uow.users.password_hash(user.id) if user is not None else None
        if user is None or stored is None or not user.enabled or user.provider != "local":
            self._hasher.verify(self._dummy_hash(), password)
            self._throttle.failed(username, ip)
            raise AuthenticationError(WRONG_CREDENTIALS)
        if not self._hasher.verify(stored, password):
            self._throttle.failed(username, ip)
            raise AuthenticationError(WRONG_CREDENTIALS)
        upgraded = self._hasher.hash(password) if self._hasher.needs_rehash(stored) else None
        with self._store() as uow:
            fresh = uow.users.get(user.id)
            if fresh is None or not fresh.enabled:
                self._throttle.failed(username, ip)
                raise AuthenticationError(WRONG_CREDENTIALS)
            if upgraded is not None and uow.users.password_hash(user.id) == stored:
                uow.users.set_password_hash(user.id, upgraded)
            user = replace(fresh, last_sign_in_ms=self._clock.now_ms())
            uow.users.save(user)
            uow.commit()
        self._throttle.succeeded(username, ip)
        token = self._sessions.create(user.id, ip, user_agent)
        return SignInResult(token, self._sessions.principal_for(user))


class ChangeOwnPassword:
    def __init__(
        self,
        store: AuthStore,
        hasher: PasswordHasher,
        sessions: SessionService,
        throttle: LoginThrottle,
        policy: Callable[[], AuthPolicy],
        clock: Clock,
    ) -> None:
        self._store = store
        self._hasher = hasher
        self._sessions = sessions
        self._throttle = throttle
        self._policy = policy
        self._clock = clock

    def __call__(self, principal: Principal, current: str, new: str, keep_token: str, ip: str) -> None:
        user_id = principal.user_id
        if user_id is None:
            raise ValidationError("The system account has no password")
        policy = self._policy()
        self._throttle.begin(principal.username, ip)
        settled = False
        try:
            # Read in a short unit of work; the slow password check runs with no write lock held.
            with self._store() as uow:
                user = uow.users.get(user_id)
                stored = uow.users.password_hash(user_id) if user is not None else None
            if user is None:
                raise NotFoundError("user not found")
            matches = stored is not None and self._hasher.verify(stored, current)
            settled = True
            if matches:
                self._throttle.succeeded(principal.username, ip)
            else:
                self._throttle.failed(principal.username, ip)
                raise AuthenticationError("Current password is wrong")
        finally:
            if not settled:
                self._throttle.release(principal.username, ip)
        check_password(new, user.username, policy.password_min_length)
        new_hash = self._hasher.hash(new)
        with self._store() as uow:
            fresh = uow.users.get(user_id)
            if fresh is None:
                raise NotFoundError("user not found")
            if uow.users.password_hash(user_id) != stored:
                raise AuthenticationError("Current password is wrong")
            uow.users.set_password_hash(user_id, new_hash)
            uow.users.save(replace(fresh, must_change_password=False))
            uow.commit()
        self._sessions.end_others(user_id, keep_token)
