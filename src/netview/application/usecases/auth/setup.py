"""First-run setup: create the built-in administrator."""

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from netview.application.ports.auth_store import AuthStore
from netview.application.ports.clock import Clock
from netview.application.ports.password_hasher import PasswordHasher
from netview.application.usecases.auth.sessions import SessionService
from netview.application.usecases.auth.sign_in import LoginThrottle, SignInResult
from netview.domain.auth import ADMIN_ROLE, AuthPolicy, User, check_password, normalize_username
from netview.domain.errors import AuthenticationError, ConflictError

SETUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SETUP_KEY = "#setup"


def make_setup_code() -> str:
    return "".join(secrets.choice(SETUP_CODE_ALPHABET) for _ in range(8))


@dataclass(frozen=True)
class SetupStatus:
    open: bool
    code_required: bool


class SetupService:
    def __init__(
        self,
        store: AuthStore,
        hasher: PasswordHasher,
        sessions: SessionService,
        throttle: LoginThrottle,
        clock: Clock,
        mode: Literal["enterprise", "home"],
        code: str | None,
        policy: Callable[[], AuthPolicy] = AuthPolicy,
    ) -> None:
        self._store = store
        self._hasher = hasher
        self._sessions = sessions
        self._throttle = throttle
        self._clock = clock
        self._mode = mode
        self._code = code
        self._policy = policy

    def _is_open(self) -> bool:
        with self._store() as uow:
            return uow.users.count() == 0

    def status(self) -> SetupStatus:
        return SetupStatus(open=self._is_open(), code_required=self._mode == "enterprise")

    def complete(
        self, code: str | None, username: str, password: str, ip: str, user_agent: str
    ) -> SignInResult:
        if not self._is_open():
            raise ConflictError("setup already done")
        if self._mode != "enterprise":
            return self._create(username, password, ip, user_agent)
        attempt = self._throttle.begin(SETUP_KEY, ip)
        expected = (self._code or "").upper()
        given = (code or "").strip().upper()
        if not expected or not hmac.compare_digest(expected.encode(), given.encode()):
            self._throttle.failed(attempt)
            raise AuthenticationError("Setup code is wrong")
        try:
            result = self._create(username, password, ip, user_agent)
        except BaseException:
            self._throttle.release(attempt)
            raise
        self._throttle.succeeded(attempt)
        return result

    def _create(self, username: str, password: str, ip: str, user_agent: str) -> SignInResult:
        name = normalize_username(username)
        check_password(password, name, self._policy().password_min_length)
        password_hash = self._hasher.hash(password)
        now = self._clock.now_ms()
        admin = User(
            id=0,
            username=name,
            display_name=name,
            email=None,
            enabled=True,
            builtin=True,
            must_change_password=False,
            role_ids=frozenset({ADMIN_ROLE}),
            provider="local",
            created_ms=now,
            last_sign_in_ms=now,
        )
        with self._store() as uow:
            try:
                created = uow.users.add(admin, password_hash, only_if_empty=True)
                uow.commit()
            except ConflictError:
                raise ConflictError("setup already done") from None
        token = self._sessions.create(created.id, ip, user_agent)
        return SignInResult(token, self._sessions.principal_for(created))
