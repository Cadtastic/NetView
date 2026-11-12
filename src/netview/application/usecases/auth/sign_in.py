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
"""One exact address, any username: locked after this many times ``lockout_failures``."""

PER_USER_PREFIX_FACTOR = 4
"""One username from anywhere in an IPv6 /64 (or an overflowing /48): rotation can't escape the limit."""

PER_PREFIX_FACTOR = 50
"""Backstop for a whole IPv6 /64, any username. High, because a LAN usually shares one /64."""

PER_SITE_FACTOR = 100
"""Backstop for the /64s of a /48 counted together once the /48 has too many /64s of its own."""

MAX_ADDRESSES_PER_PREFIX = 8
"""Exact-address counts kept per /64; beyond that, its addresses are counted only by the /64 tiers."""

KNOWN_DEVICE_MS = 30 * 24 * 3600 * 1000
"""An exact address that signed in to an account within this long skips that account's network-wide limit."""

MAX_KNOWN_PER_USER = 16
MAX_KNOWN = 10_000
"""Known devices kept per username and overall; the oldest go first."""

MAX_PREFIXES_PER_SITE = 16
"""/64 counts kept per /48; beyond that, its /64s are counted together at the /48."""

Key = tuple[str, str]
CAP_MARKERS = ("*", "/", "//")
"""First element of the keys that carry the caps; they are never dropped to make room."""


def _address_key(ip: str) -> Key:
    return ("*", _source(ip))  # "*" can't be a normalized username, and the fallback keys start with "~"


@functools.lru_cache(maxsize=4096)
def _networks(source: str) -> tuple[str, str] | None:
    """(/64, /48) of an IPv6 source, or None for IPv4 and anything unparseable."""
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        return (
            str(ipaddress.IPv6Network((address, 64), strict=False)),
            str(ipaddress.IPv6Network((address, 48), strict=False)),
        )
    return None


@dataclass(frozen=True)
class Attempt:
    """What ``begin`` reserved; hand it back to exactly one of ``failed``, ``succeeded`` or ``release``."""

    keys: tuple[Key, ...]
    exact: Key
    """(username, exact address): the only count a success clears, and what it marks as a known device."""


class LoginThrottle:
    """In-memory failure counts within ``lockout_window_s``, in tiers that each lock on their own.

    IPv4 (and anything that isn't IPv6):
    - username + exact address: ``lockout_failures``;
    - exact address, any username: ``PER_ADDRESS_FACTOR`` x that.

    IPv6 adds, so one host can't escape by rotating through its /64:
    - username + /64: ``PER_USER_PREFIX_FACTOR`` x that;
    - whole /64, any username: ``PER_PREFIX_FACTOR`` x that, a high backstop so one noisy host doesn't lock
      out its LAN neighbours.
    A /64 keeps at most ``MAX_ADDRESSES_PER_PREFIX`` exact-address counts and a /48 at most
    ``MAX_PREFIXES_PER_SITE`` /64 counts; past those, the overflow is counted together one level up
    (username + /48 and whole /48), so rotation can't fill the table.

    ``begin`` reserves an attempt on every key it uses before the slow password check and returns them as an
    ``Attempt``; settling acts on exactly those keys. Live state is never forgotten to make room: only
    per-username counts that are neither locked nor in use may be dropped. If nothing can be dropped, new keys
    are refused.
    """

    SWEEP_EVERY_MS = 60_000

    def __init__(self, clock: Clock, policy: Callable[[], AuthPolicy], max_keys: int = 100_000) -> None:
        self._clock = clock
        self._policy = policy
        self._max_keys = max_keys
        self._last_sweep = 0
        self._lock = threading.Lock()
        self._failures: dict[Key, list[int]] = {}
        self._locked_until: dict[Key, int] = {}
        self._pending: dict[Key, int] = {}
        self._prefix_addresses: dict[str, set[str]] = {}
        """/64 -> addresses with an exact-address count; pruned as it is read, so it stays small."""
        self._site_prefixes: dict[str, set[str]] = {}
        """/48 -> /64s with a /64 count; pruned as it is read."""
        self._known: dict[Key, int] = {}
        """(username, exact address) -> last successful sign-in. Only a correct password adds an entry."""

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
        live = self._live()
        for prefix in list(self._prefix_addresses):
            self._pruned(self._prefix_addresses, prefix, "*", live)
        for site in list(self._site_prefixes):
            self._pruned(self._site_prefixes, site, "/", live)
        for key in [k for k, t in self._known.items() if now - t > KNOWN_DEVICE_MS]:
            del self._known[key]

    @staticmethod
    def _pruned(index: dict[str, set[str]], group: str, marker: str, live: set[Key]) -> set[str]:
        members = {m for m in index.get(group, ()) if (marker, m) in live}
        if members:
            index[group] = members
        else:
            index.pop(group, None)
        return members

    @staticmethod
    def _limit(key: Key, policy: AuthPolicy) -> int:
        base = policy.lockout_failures
        if key[0] == "*":
            return base * PER_ADDRESS_FACTOR
        if key[0] == "/":
            return base * PER_PREFIX_FACTOR
        if key[0] == "//":
            return base * PER_SITE_FACTOR
        if key[1].startswith("/"):  # a username across a /64 or an overflowing /48
            return base * PER_USER_PREFIX_FACTOR
        return base

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

    def _plan(self, username: str, ip: str, live: set[Key], now: int) -> list[Key]:
        """Every key this attempt counts against."""
        user, address = _key(username, ip), _address_key(ip)
        nets = _networks(address[1])
        if nets is None:
            return [user, address]
        p64, p48 = nets
        name = user[0]
        # A device that signed in to this account recently isn't held back by someone else burning the
        # account's network-wide allowance from the same LAN; its own address tiers still apply.
        known = now - self._known.get(user, -KNOWN_DEVICE_MS - 1) <= KNOWN_DEVICE_MS
        tracked_p64 = self._pruned(self._site_prefixes, p48, "/", live)
        if ("/", p64) not in live and len(tracked_p64) >= MAX_PREFIXES_PER_SITE:
            keys = [("//", p48)] if known else [(name, "//" + p48), ("//", p48)]
        else:
            keys = [("/", p64)] if known else [(name, "/" + p64), ("/", p64)]
        tracked = self._pruned(self._prefix_addresses, p64, "*", live)
        # A known device always keeps its own limits (its entries exist only after a correct password, so they
        # can't be used to fill the table); other addresses only while the /64 has room for them.
        if known or address in live or len(tracked) < MAX_ADDRESSES_PER_PREFIX:
            keys += [user, address]
        return keys

    def begin(self, username: str, ip: str) -> Attempt:
        now = self._clock.now_ms()
        policy = self._policy()
        with self._lock:
            self._sweep(now, policy)
            live = self._live()
            keys = self._plan(username, ip, live, now)
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
            # Index the new cap keys only now that they are reserved (live).
            for key in keys:
                nets = _networks(key[1]) if key[0] in ("*", "/") else None
                if key[0] == "*" and nets:
                    self._prefix_addresses.setdefault(nets[0], set()).add(key[1])
                elif key[0] == "/":
                    site = str(ipaddress.IPv6Network(key[1]).supernet(new_prefix=48))
                    self._site_prefixes.setdefault(site, set()).add(key[1])
            return Attempt(tuple(keys), _key(username, ip))

    def _make_room(self, needed: int, now: int, policy: AuthPolicy) -> None:
        """Expire what can be expired, then drop the oldest per-username counts not locked or in use."""
        self._sweep(now, policy, force=True)

        def covered(k: Key) -> bool:
            """A username's network count whose network backstop is locked: the backstop refuses for it."""
            if k[1].startswith("//"):
                return ("//", k[1][2:]) in self._locked_until
            return k[1].startswith("/") and ("/", k[1][1:]) in self._locked_until

        spare = [
            k
            for k in self._failures
            if k[0] not in CAP_MARKERS
            and (not k[1].startswith("/") or covered(k))  # a username's network count is a cap too
            and k not in self._locked_until
            and self._pending.get(k, 0) == 0
        ]
        spare.sort(key=lambda k: self._failures[k][-1])  # oldest first
        for key in spare[:needed]:
            del self._failures[key]

    def _remember(self, device: Key, now: int) -> None:
        """Mark a (username, exact address) as known, keeping the newest per username and overall."""
        self._known.pop(device, None)
        self._known[device] = now  # dicts keep insertion order, so the oldest come first
        mine = [k for k in self._known if k[0] == device[0]]
        for old in mine[: max(0, len(mine) - MAX_KNOWN_PER_USER)]:
            del self._known[old]
        for old in list(self._known)[: max(0, len(self._known) - MAX_KNOWN)]:
            del self._known[old]

    def _settle(self, key: Key) -> None:
        left = self._pending.get(key, 0) - 1
        if left > 0:
            self._pending[key] = left
        else:
            self._pending.pop(key, None)

    def release(self, attempt: Attempt) -> None:
        """Settle an attempt that ended in neither a failure nor a success."""
        with self._lock:
            for key in attempt.keys:
                self._settle(key)

    def _record_failure(self, key: Key, now: int, policy: AuthPolicy) -> None:
        recent = [t for t in self._failures.get(key, []) if now - t <= policy.lockout_window_s * 1000]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= self._limit(key, policy):
            self._locked_until[key] = now + policy.lockout_s * 1000

    def failed(self, attempt: Attempt) -> None:
        now = self._clock.now_ms()
        policy = self._policy()
        with self._lock:
            for key in attempt.keys:
                self._settle(key)
                self._record_failure(key, now, policy)

    def succeeded(self, attempt: Attempt) -> None:
        """Clear only the exact-address count and remember the device; network counts expire on their own."""
        now = self._clock.now_ms()
        with self._lock:
            for key in attempt.keys:
                self._settle(key)
            self._failures.pop(attempt.exact, None)
            self._locked_until.pop(attempt.exact, None)
            self._remember(attempt.exact, now)


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
        attempt = self._throttle.begin(username, ip)
        try:
            return self._sign_in(attempt, username, password, ip, user_agent)
        except AuthenticationError:
            raise
        except BaseException:
            self._throttle.release(attempt)
            raise

    def _sign_in(
        self, attempt: Attempt, username: str, password: str, ip: str, user_agent: str
    ) -> SignInResult:
        try:
            name = normalize_username(username)
        except ValidationError:
            self._hasher.verify(self._dummy_hash(), password)
            self._throttle.failed(attempt)
            raise AuthenticationError(WRONG_CREDENTIALS) from None
        # Argon2 is slow and SQLite has one writer: never hash while a unit of work is open.
        with self._store() as uow:
            user = uow.users.by_username(name)
            stored = uow.users.password_hash(user.id) if user is not None else None
        if user is None or stored is None or not user.enabled or user.provider != "local":
            self._hasher.verify(self._dummy_hash(), password)
            self._throttle.failed(attempt)
            raise AuthenticationError(WRONG_CREDENTIALS)
        if not self._hasher.verify(stored, password):
            self._throttle.failed(attempt)
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
                self._throttle.failed(attempt)
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
            self._throttle.failed(attempt)
            raise AuthenticationError(WRONG_CREDENTIALS) from None
        self._throttle.succeeded(attempt)
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
        attempt = self._throttle.begin(principal.username, ip)
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
                self._throttle.succeeded(attempt)
            else:
                self._throttle.failed(attempt)
                raise AuthenticationError("Current password is wrong")
        finally:
            if not settled:
                self._throttle.release(attempt)
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
