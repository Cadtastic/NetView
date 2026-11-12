"""Password sign-in, brute-force throttling and changing your own password."""

import functools
import hashlib
import ipaddress
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


def _source(ip: str) -> str:
    """The client address in one canonical form (an IPv4-mapped IPv6 address counts as the IPv4 one).

    Exact addresses, not /64s: on a LAN every IPv6 device usually shares one /64, so grouping would let
    one bad actor lock out all of their neighbours.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


def _key(username: str, ip: str) -> tuple[str, str]:
    try:
        name = normalize_username(username)
    except ValidationError:
        # Unvalidated input: bound it so a stream of long, unique names cannot grow memory.
        name = "~" + hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()[:16]
    return (name, _source(ip))


PER_ADDRESS_FACTOR = 4
"""An address is locked after this many times ``lockout_failures`` failures across any usernames."""

PER_PREFIX_FACTOR = 20
"""An IPv6 /64 is locked after this many times ``lockout_failures`` failures across its addresses."""

MAX_ADDRESSES_PER_PREFIX = 64
"""Exact-address counts kept per IPv6 /64; beyond that, its addresses are counted only by the /64."""

Key = tuple[str, str]


def _address_key(ip: str) -> Key:
    return ("*", _source(ip))  # "*" can't be a normalized username, and the fallback keys start with "~"


@functools.lru_cache(maxsize=4096)
def _prefix(source: str) -> str | None:
    """The /64 an IPv6 source belongs to, or None for IPv4 and anything unparseable."""
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return None


class LoginThrottle:
    """In-memory failure counter in three tiers, all within ``lockout_window_s``.

    - per (normalized username, exact address): ``lockout_failures``;
    - per exact address, any username: ``PER_ADDRESS_FACTOR`` x that;
    - per IPv6 /64, any username: ``PER_PREFIX_FACTOR`` x that, so rotating through a /64 doesn't escape
      the address tier, while one noisy address doesn't lock out its LAN neighbours.

    ``begin`` reserves an attempt on every key it uses before the slow password check, so parallel
    requests can't all pass a limit before any failure is recorded. Every ``begin`` must be settled by
    exactly one of ``failed``, ``succeeded`` or ``release``; they act on the keys ``begin`` reserved.

    Live state is never forgotten to make room: only per-username counts that are neither locked nor in
    use may be dropped (address and /64 counts carry the caps). A /64 keeps at most
    ``MAX_ADDRESSES_PER_PREFIX`` exact-address counts, so rotation can't fill the table. If nothing can
    be dropped, new keys are refused.
    """

    SWEEP_EVERY_MS = 60_000

    def __init__(self, clock: Clock, policy: Callable[[], AuthPolicy], max_keys: int = 10_000) -> None:
        self._clock = clock
        self._policy = policy
        self._max_keys = max_keys
        self._last_sweep = 0
        self._lock = threading.Lock()
        self._failures: dict[Key, list[int]] = {}
        self._locked_until: dict[Key, int] = {}
        self._pending: dict[Key, int] = {}

    def _live(self) -> set[Key]:
        return set(self._failures) | set(self._locked_until) | set(self._pending)

    def _sweep(self, now: int, policy: AuthPolicy, *, force: bool = False) -> None:
        """Forget only what has expired: locks that ran out and failures older than the window."""
        if not force and now - self._last_sweep < self.SWEEP_EVERY_MS:
            return
        self._last_sweep = now
        window = policy.lockout_window_s * 1000
        for key in [k for k, until in self._locked_until.items() if now >= until]:
            del self._locked_until[key]
            self._failures.pop(key, None)
        for key in [k for k, times in self._failures.items() if now - times[-1] > window]:
            if key not in self._locked_until:
                del self._failures[key]

    @staticmethod
    def _limit(key: Key, policy: AuthPolicy) -> int:
        if key[0] == "*":
            return policy.lockout_failures * PER_ADDRESS_FACTOR
        if key[0] == "/":
            return policy.lockout_failures * PER_PREFIX_FACTOR
        return policy.lockout_failures

    def _check(self, key: Key, now: int, policy: AuthPolicy) -> None:
        until = self._locked_until.get(key)
        if until is not None:
            if now < until:
                raise TooManyAttemptsError()
            del self._locked_until[key]
            self._failures.pop(key, None)
        recent = [t for t in self._failures.get(key, []) if now - t <= policy.lockout_window_s * 1000]
        if len(recent) + self._pending.get(key, 0) >= self._limit(key, policy):
            raise TooManyAttemptsError()

    def _keys_to_reserve(self, username: str, ip: str, live: set[Key]) -> list[Key]:
        user, address = _key(username, ip), _address_key(ip)
        prefix = _prefix(address[1])
        if prefix is None:
            return [user, address]
        keys = [user, ("/", prefix)]
        in_prefix = sum(1 for k in live if k[0] == "*" and _prefix(k[1]) == prefix)
        if address in live or in_prefix < MAX_ADDRESSES_PER_PREFIX:
            keys.append(address)
        return keys

    def _reserved(self, username: str, ip: str) -> list[Key]:
        """The keys a ``begin`` for this attempt reserved (those with an attempt in progress)."""
        address = _address_key(ip)
        prefix = _prefix(address[1])
        candidates = [_key(username, ip), address] + ([("/", prefix)] if prefix else [])
        return [k for k in candidates if self._pending.get(k, 0) > 0]

    def begin(self, username: str, ip: str) -> None:
        now = self._clock.now_ms()
        policy = self._policy()
        with self._lock:
            self._sweep(now, policy)
            live = self._live()
            keys = self._keys_to_reserve(username, ip, live)
            for key in keys:
                self._check(key, now, policy)
            new = [k for k in keys if k not in live]
            if new and len(live) + len(new) > self._max_keys:
                self._make_room(len(live) + len(new) - self._max_keys, now, policy)
                live = self._live()
                new = [k for k in keys if k not in live]
                if new and len(live) + len(new) > self._max_keys:
                    # Everything left is locked, in use, or a cap: refuse rather than forget it.
                    raise TooManyAttemptsError()
            for key in keys:
                self._pending[key] = self._pending.get(key, 0) + 1

    def _make_room(self, needed: int, now: int, policy: AuthPolicy) -> None:
        """Expire what can be expired, then drop the oldest per-username counts not locked or in use."""
        self._sweep(now, policy, force=True)
        spare = [
            k
            for k in self._failures
            if k[0] not in ("*", "/") and k not in self._locked_until and self._pending.get(k, 0) == 0
        ]
        spare.sort(key=lambda k: self._failures[k][-1])  # oldest first
        for key in spare[:needed]:
            del self._failures[key]

    def _settle(self, key: Key) -> None:
        left = self._pending.get(key, 0) - 1
        if left > 0:
            self._pending[key] = left
        else:
            self._pending.pop(key, None)

    def release(self, username: str, ip: str) -> None:
        """Settle a ``begin`` that ended in neither a failure nor a success."""
        with self._lock:
            for key in self._reserved(username, ip):
                self._settle(key)

    def _record_failure(self, key: Key, now: int, policy: AuthPolicy) -> None:
        recent = [t for t in self._failures.get(key, []) if now - t <= policy.lockout_window_s * 1000]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= self._limit(key, policy):
            self._locked_until[key] = now + policy.lockout_s * 1000

    def failed(self, username: str, ip: str) -> None:
        now = self._clock.now_ms()
        policy = self._policy()
        with self._lock:
            for key in self._reserved(username, ip):
                self._settle(key)
                self._record_failure(key, now, policy)

    def succeeded(self, username: str, ip: str) -> None:
        """Clear the username's count; address and /64 counts stay, so one good login can't reset them."""
        user = _key(username, ip)
        with self._lock:
            for key in self._reserved(username, ip):
                self._settle(key)
            self._failures.pop(user, None)
            self._locked_until.pop(user, None)


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
            # Fail closed if anything changed while the slow check ran: disabled, no longer a local
            # account, or a new password (an admin reset). The checked password is no longer the one.
            if (
                fresh is None
                or not fresh.enabled
                or fresh.provider != "local"
                or uow.users.password_hash(user.id) != stored
            ):
                self._throttle.failed(username, ip)
                raise AuthenticationError(WRONG_CREDENTIALS)
            if upgraded is not None:
                uow.users.set_password_hash(user.id, upgraded)
            user = replace(fresh, last_sign_in_ms=self._clock.now_ms())
            uow.users.save(user)
            uow.commit()
        try:
            # Refused if a reset bumped the version after the read above.
            token = self._sessions.create(user.id, ip, user_agent, security_version=user.security_version)
        except AuthenticationError:
            self._throttle.failed(username, ip)
            raise AuthenticationError(WRONG_CREDENTIALS) from None
        self._throttle.succeeded(username, ip)
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
            uow.users.save(
                replace(fresh, must_change_password=False, security_version=fresh.security_version + 1)
            )
            uow.commit()
        self._sessions.end_others(user_id, keep_token)
