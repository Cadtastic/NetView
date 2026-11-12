"""In-memory auth store, used by tests and as the reference for the store contract."""

import copy
import threading
from dataclasses import dataclass, field, replace
from types import TracebackType

from netview.application.ports.auth_store import SessionRecord
from netview.domain.auth import ADMIN_ROLE, DEFAULT_ROLE, Role, User
from netview.domain.errors import ConflictError, NotFoundError


@dataclass
class _Data:
    users: dict[int, User] = field(default_factory=dict)
    hashes: dict[int, str] = field(default_factory=dict)
    roles: dict[str, Role] = field(default_factory=dict)
    sessions: dict[str, SessionRecord] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    next_id: int = 1


class _Users:
    def __init__(self, uow: "InMemoryAuthUnitOfWork") -> None:
        self._uow = uow
        self._d = uow.data

    def get(self, user_id: int) -> User | None:
        return self._d.users.get(user_id)

    def by_username(self, username: str) -> User | None:
        return next((u for u in self._d.users.values() if u.username == username), None)

    def list(self) -> list[User]:
        return sorted(self._d.users.values(), key=lambda u: u.id)

    def count(self) -> int:
        return len(self._d.users)

    def add(self, user: User, password_hash: str | None, *, only_if_empty: bool = False) -> User:
        with self._uow.lock:
            if only_if_empty:
                if self._d.users or self._uow.shared.users:
                    raise ConflictError("users already exist")
                self._uow.guard_empty = True
            if self.by_username(user.username) is not None:
                raise ConflictError("username already exists")
            if user.builtin and any(u.builtin for u in self._d.users.values()):
                raise ConflictError("built-in user already exists")
            stored = replace(user, id=self._d.next_id)
            self._d.next_id += 1
            self._d.users[stored.id] = stored
            if password_hash is not None:
                self._d.hashes[stored.id] = password_hash
            return stored

    def save(self, user: User) -> None:
        if user.id not in self._d.users:
            raise NotFoundError("user not found")
        other = self.by_username(user.username)
        if other is not None and other.id != user.id:
            raise ConflictError("username already exists")
        self._d.users[user.id] = user

    def remove(self, user_id: int) -> None:
        self._d.users.pop(user_id, None)
        self._d.hashes.pop(user_id, None)
        for token in [t for t, s in self._d.sessions.items() if s.user_id == user_id]:
            del self._d.sessions[token]

    def password_hash(self, user_id: int) -> str | None:
        return self._d.hashes.get(user_id)

    def set_password_hash(self, user_id: int, hash: str) -> None:
        if user_id not in self._d.users:
            raise NotFoundError("user not found")
        self._d.hashes[user_id] = hash


class _Roles:
    def __init__(self, d: _Data) -> None:
        self._d = d

    def get(self, role_id: str) -> Role | None:
        return self._d.roles.get(role_id)

    def list(self) -> list[Role]:
        return sorted(self._d.roles.values(), key=lambda r: (not r.builtin, r.name.casefold()))

    def add(self, role: Role) -> None:
        if role.id in self._d.roles:
            raise ConflictError("role already exists")
        self._d.roles[role.id] = role

    def save(self, role: Role) -> None:
        if role.id not in self._d.roles:
            raise NotFoundError("role not found")
        self._d.roles[role.id] = role

    def remove(self, role_id: str) -> None:
        self._d.roles.pop(role_id, None)
        for uid, user in list(self._d.users.items()):
            if role_id in user.role_ids:
                self._d.users[uid] = replace(user, role_ids=user.role_ids - {role_id})


class _Sessions:
    def __init__(self, d: _Data) -> None:
        self._d = d

    def add(self, s: SessionRecord) -> None:
        self._d.sessions[s.token_hash] = s

    def get(self, token_hash: str) -> SessionRecord | None:
        return self._d.sessions.get(token_hash)

    def touch(self, token_hash: str, now_ms: int) -> None:
        s = self._d.sessions.get(token_hash)
        if s is not None:
            self._d.sessions[token_hash] = replace(s, last_seen_ms=now_ms)

    def remove(self, token_hash: str) -> None:
        self._d.sessions.pop(token_hash, None)

    def remove_for_user(self, user_id: int) -> int:
        doomed = [t for t, s in self._d.sessions.items() if s.user_id == user_id]
        for t in doomed:
            del self._d.sessions[t]
        return len(doomed)


class _Settings:
    def __init__(self, d: _Data) -> None:
        self._d = d

    def get(self, key: str) -> str | None:
        return self._d.settings.get(key)

    def set(self, key: str, value: str) -> None:
        self._d.settings[key] = value


class InMemoryAuthUnitOfWork:
    """Works on a private copy of the shared data; ``commit`` writes it back."""

    def __init__(self, shared: _Data, lock: threading.Lock) -> None:
        self.shared = shared
        self.lock = lock
        self.data = copy.deepcopy(shared)
        self.guard_empty = False
        self.committed = False
        self.users = _Users(self)
        self.roles = _Roles(self.data)
        self.sessions = _Sessions(self.data)
        self.settings = _Settings(self.data)

    def commit(self) -> None:
        with self.lock:
            if self.guard_empty and self.shared.users:
                raise ConflictError("users already exist")
            snapshot = copy.deepcopy(self.data)
            self.shared.__dict__.update(snapshot.__dict__)
            self.committed = True

    def __enter__(self) -> "InMemoryAuthUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self.committed:
            self.data.__dict__.update(copy.deepcopy(self.shared).__dict__)


class InMemoryAuthStore:
    """Every unit of work it creates shares one store. Seeds the two built-in roles."""

    def __init__(self) -> None:
        self._shared = _Data()
        self._lock = threading.Lock()
        self._shared.roles[ADMIN_ROLE] = Role(ADMIN_ROLE, "Administrator", True, frozenset())
        self._shared.roles[DEFAULT_ROLE] = Role(DEFAULT_ROLE, "Default", True, frozenset({"core.view"}))

    def __call__(self) -> InMemoryAuthUnitOfWork:
        return InMemoryAuthUnitOfWork(self._shared, self._lock)
