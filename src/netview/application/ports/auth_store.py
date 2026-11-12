"""Auth store port: users, roles, sessions and auth settings, with their own unit of work."""

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

from netview.domain.auth import Role, User


@dataclass(frozen=True)
class SessionRecord:
    token_hash: str
    user_id: int
    created_ms: int
    last_seen_ms: int
    ip: str
    user_agent: str


class UserRepository(Protocol):
    def get(self, user_id: int) -> User | None: ...
    def by_username(self, username: str) -> User | None: ...
    def list(self) -> list[User]: ...
    def count(self) -> int: ...
    def add(self, user: User, password_hash: str | None, *, only_if_empty: bool = False) -> User:
        """Store the user and assign its ``id``.

        Raises ``ConflictError`` on a duplicate username, a second built-in user, or, when
        ``only_if_empty`` is true, when any user already exists (the first-run setup race guard).
        """
        ...

    def save(self, user: User) -> None: ...
    def remove(self, user_id: int) -> None: ...
    def password_hash(self, user_id: int) -> str | None: ...
    def set_password_hash(self, user_id: int, hash: str) -> None: ...


class RoleRepository(Protocol):
    def get(self, role_id: str) -> Role | None: ...
    def list(self) -> list[Role]: ...
    def add(self, role: Role) -> None: ...
    def save(self, role: Role) -> None: ...
    def remove(self, role_id: str) -> None:
        """Delete the role and take it away from every user."""
        ...


class SessionRepository(Protocol):
    def add(self, s: SessionRecord) -> None: ...
    def get(self, token_hash: str) -> SessionRecord | None: ...
    def touch(self, token_hash: str, now_ms: int) -> None: ...
    def remove(self, token_hash: str) -> None: ...
    def remove_for_user(self, user_id: int) -> int: ...


class SettingsRepository(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class AuthUnitOfWork(Protocol):
    users: UserRepository
    roles: RoleRepository
    sessions: SessionRepository
    settings: SettingsRepository

    def commit(self) -> None: ...
    def __enter__(self) -> "AuthUnitOfWork": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless ``commit`` was called."""
        ...


AuthStore = Callable[[], AuthUnitOfWork]
