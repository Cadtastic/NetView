"""SQL auth store: users, roles, sessions and auth settings in the core database.

Reads and writes go through Core statements on the mapped tables, so nothing depends on the ORM
identity map. NetView's engine starts SQLite transactions with ``BEGIN IMMEDIATE``, which makes the
count-then-insert in ``SqlUserRepository.add(only_if_empty=True)`` atomic; the partial unique index
``uq_users_one_builtin`` is the backstop on any database.
"""

from collections.abc import Iterable
from types import TracebackType
from typing import Any, cast

from sqlalchemy import CursorResult, Table, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from netview.application.ports.auth_store import SessionRecord
from netview.domain.auth import Role, User
from netview.domain.errors import ConflictError, NotFoundError
from netview.infrastructure.db.models import (
    AppSettingRow,
    RolePermissionRow,
    RoleRow,
    SessionRow,
    UserLoginRow,
    UserRoleRow,
    UserRow,
)

_USERS = cast(Table, UserRow.__table__)
_LOGINS = cast(Table, UserLoginRow.__table__)
_ROLES = cast(Table, RoleRow.__table__)
_ROLE_PERMS = cast(Table, RolePermissionRow.__table__)
_USER_ROLES = cast(Table, UserRoleRow.__table__)
_SESSIONS = cast(Table, SessionRow.__table__)
_SETTINGS = cast(Table, AppSettingRow.__table__)

_LOCAL = "local"


def _rowcount(result: Any) -> int:
    return int(cast("CursorResult[Any]", result).rowcount)


def _to_user(row: Any, role_ids: Iterable[str]) -> User:
    return User(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        email=row.email,
        enabled=bool(row.enabled),
        builtin=bool(row.builtin),
        must_change_password=bool(row.must_change_password),
        role_ids=frozenset(role_ids),
        provider=row.provider,
        created_ms=row.created_ms,
        last_sign_in_ms=row.last_sign_in_ms,
    )


class SqlUserRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _role_ids(self, user_id: int) -> list[str]:
        return list(
            self._s.execute(select(_USER_ROLES.c.role_id).where(_USER_ROLES.c.user_id == user_id)).scalars()
        )

    def get(self, user_id: int) -> User | None:
        row = self._s.execute(select(_USERS).where(_USERS.c.id == user_id)).first()
        return None if row is None else _to_user(row, self._role_ids(user_id))

    def by_username(self, username: str) -> User | None:
        row = self._s.execute(select(_USERS).where(_USERS.c.username == username)).first()
        return None if row is None else _to_user(row, self._role_ids(row.id))

    def list(self) -> list[User]:
        rows = self._s.execute(select(_USERS).order_by(_USERS.c.id)).all()
        by_user: dict[int, list[str]] = {}
        for user_id, role_id in self._s.execute(select(_USER_ROLES.c.user_id, _USER_ROLES.c.role_id)):
            by_user.setdefault(user_id, []).append(role_id)
        return [_to_user(r, by_user.get(r.id, [])) for r in rows]

    def count(self) -> int:
        return int(self._s.execute(select(func.count()).select_from(_USERS)).scalar_one())

    def _builtin_exists(self) -> bool:
        return bool(
            self._s.execute(select(func.count()).select_from(_USERS).where(_USERS.c.builtin)).scalar_one()
        )

    def add(self, user: User, password_hash: str | None, *, only_if_empty: bool = False) -> User:
        if only_if_empty and self.count() > 0:
            raise ConflictError("users already exist")
        if self.by_username(user.username) is not None:
            raise ConflictError("username already exists")
        if user.builtin and self._builtin_exists():
            raise ConflictError("setup already done")
        try:
            result = self._s.execute(
                insert(_USERS).values(
                    username=user.username,
                    display_name=user.display_name,
                    email=user.email,
                    enabled=user.enabled,
                    builtin=user.builtin,
                    must_change_password=user.must_change_password,
                    provider=user.provider,
                    created_ms=user.created_ms,
                    last_sign_in_ms=user.last_sign_in_ms,
                )
            )
            user_id = int(cast("tuple[Any, ...]", cast("CursorResult[Any]", result).inserted_primary_key)[0])
            self._s.execute(
                insert(_LOGINS).values(
                    user_id=user_id,
                    provider=user.provider,
                    subject=user.username,
                    password_hash=password_hash,
                )
            )
            if user.role_ids:
                self._s.execute(
                    insert(_USER_ROLES), [{"user_id": user_id, "role_id": r} for r in sorted(user.role_ids)]
                )
        except IntegrityError as exc:
            raise ConflictError(_conflict_message(exc)) from exc
        return User(**{**user.__dict__, "id": user_id})

    def save(self, user: User) -> None:
        current = self._s.execute(
            select(_USERS.c.username).where(_USERS.c.id == user.id)
        ).scalar_one_or_none()
        if current is None:
            raise NotFoundError("user not found")
        try:
            self._s.execute(
                update(_USERS)
                .where(_USERS.c.id == user.id)
                .values(
                    username=user.username,
                    display_name=user.display_name,
                    email=user.email,
                    enabled=user.enabled,
                    builtin=user.builtin,
                    must_change_password=user.must_change_password,
                    provider=user.provider,
                    last_sign_in_ms=user.last_sign_in_ms,
                )
            )
            if current != user.username:
                self._s.execute(
                    update(_LOGINS)
                    .where(_LOGINS.c.user_id == user.id, _LOGINS.c.provider == user.provider)
                    .values(subject=user.username)
                )
            self._s.execute(delete(_USER_ROLES).where(_USER_ROLES.c.user_id == user.id))
            if user.role_ids:
                self._s.execute(
                    insert(_USER_ROLES), [{"user_id": user.id, "role_id": r} for r in sorted(user.role_ids)]
                )
        except IntegrityError as exc:
            raise ConflictError(_conflict_message(exc)) from exc

    def remove(self, user_id: int) -> None:
        self._s.execute(delete(_SESSIONS).where(_SESSIONS.c.user_id == user_id))
        self._s.execute(delete(_USER_ROLES).where(_USER_ROLES.c.user_id == user_id))
        self._s.execute(delete(_LOGINS).where(_LOGINS.c.user_id == user_id))
        self._s.execute(delete(_USERS).where(_USERS.c.id == user_id))

    def password_hash(self, user_id: int) -> str | None:
        return self._s.execute(
            select(_LOGINS.c.password_hash).where(_LOGINS.c.user_id == user_id, _LOGINS.c.provider == _LOCAL)
        ).scalar_one_or_none()

    def set_password_hash(self, user_id: int, hash: str) -> None:
        username = self._s.execute(
            select(_USERS.c.username).where(_USERS.c.id == user_id)
        ).scalar_one_or_none()
        if username is None:
            raise NotFoundError("user not found")
        changed = self._s.execute(
            update(_LOGINS)
            .where(_LOGINS.c.user_id == user_id, _LOGINS.c.provider == _LOCAL)
            .values(password_hash=hash)
        )
        if _rowcount(changed) == 0:
            self._s.execute(
                insert(_LOGINS).values(user_id=user_id, provider=_LOCAL, subject=username, password_hash=hash)
            )


def _conflict_message(exc: IntegrityError) -> str:
    text = str(exc.orig).lower()
    if "builtin" in text:
        return "setup already done"
    if "username" in text:
        return "username already exists"
    return "conflicts with existing data"


class SqlRoleRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _permissions(self, role_id: str) -> frozenset[str]:
        return frozenset(
            self._s.execute(
                select(_ROLE_PERMS.c.permission_id).where(_ROLE_PERMS.c.role_id == role_id)
            ).scalars()
        )

    def get(self, role_id: str) -> Role | None:
        row = self._s.execute(select(_ROLES).where(_ROLES.c.id == role_id)).first()
        if row is None:
            return None
        return Role(row.id, row.name, bool(row.builtin), self._permissions(role_id))

    def list(self) -> list[Role]:
        perms: dict[str, set[str]] = {}
        for role_id, permission_id in self._s.execute(
            select(_ROLE_PERMS.c.role_id, _ROLE_PERMS.c.permission_id)
        ):
            perms.setdefault(role_id, set()).add(permission_id)
        roles = [
            Role(r.id, r.name, bool(r.builtin), frozenset(perms.get(r.id, ())))
            for r in self._s.execute(select(_ROLES)).all()
        ]
        return sorted(roles, key=lambda r: (not r.builtin, r.name.casefold()))

    def add(self, role: Role) -> None:
        if self._s.execute(select(_ROLES.c.id).where(_ROLES.c.id == role.id)).first() is not None:
            raise ConflictError("role already exists")
        self._s.execute(insert(_ROLES).values(id=role.id, name=role.name, builtin=role.builtin))
        self._set_permissions(role)

    def save(self, role: Role) -> None:
        changed = self._s.execute(
            update(_ROLES).where(_ROLES.c.id == role.id).values(name=role.name, builtin=role.builtin)
        )
        if _rowcount(changed) == 0:
            raise NotFoundError("role not found")
        self._s.execute(delete(_ROLE_PERMS).where(_ROLE_PERMS.c.role_id == role.id))
        self._set_permissions(role)

    def _set_permissions(self, role: Role) -> None:
        if role.permissions:
            self._s.execute(
                insert(_ROLE_PERMS),
                [{"role_id": role.id, "permission_id": p} for p in sorted(role.permissions)],
            )

    def remove(self, role_id: str) -> None:
        self._s.execute(delete(_USER_ROLES).where(_USER_ROLES.c.role_id == role_id))
        self._s.execute(delete(_ROLE_PERMS).where(_ROLE_PERMS.c.role_id == role_id))
        self._s.execute(delete(_ROLES).where(_ROLES.c.id == role_id))


class SqlSessionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, s: SessionRecord) -> None:
        self._s.execute(
            insert(_SESSIONS).values(
                token_hash=s.token_hash,
                user_id=s.user_id,
                created_ms=s.created_ms,
                last_seen_ms=s.last_seen_ms,
                ip=s.ip,
                user_agent=s.user_agent,
            )
        )

    def get(self, token_hash: str) -> SessionRecord | None:
        row = self._s.execute(select(_SESSIONS).where(_SESSIONS.c.token_hash == token_hash)).first()
        if row is None:
            return None
        return SessionRecord(
            row.token_hash, row.user_id, row.created_ms, row.last_seen_ms, row.ip, row.user_agent
        )

    def touch(self, token_hash: str, now_ms: int) -> None:
        self._s.execute(
            update(_SESSIONS).where(_SESSIONS.c.token_hash == token_hash).values(last_seen_ms=now_ms)
        )

    def remove(self, token_hash: str) -> None:
        self._s.execute(delete(_SESSIONS).where(_SESSIONS.c.token_hash == token_hash))

    def remove_for_user(self, user_id: int) -> int:
        return _rowcount(self._s.execute(delete(_SESSIONS).where(_SESSIONS.c.user_id == user_id)))


class SqlSettingsRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, key: str) -> str | None:
        return self._s.execute(select(_SETTINGS.c.value).where(_SETTINGS.c.key == key)).scalar_one_or_none()

    def set(self, key: str, value: str) -> None:
        changed = self._s.execute(update(_SETTINGS).where(_SETTINGS.c.key == key).values(value=value))
        if _rowcount(changed) == 0:
            self._s.execute(insert(_SETTINGS).values(key=key, value=value))


class SqlAuthUnitOfWork:
    """One session per unit of work; rolls back on exit unless committed."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session: Session = session_factory()
        self.users = SqlUserRepository(self.session)
        self.roles = SqlRoleRepository(self.session)
        self.sessions = SqlSessionRepository(self.session)
        self.settings = SqlSettingsRepository(self.session)
        self.committed = False

    def commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(_conflict_message(exc)) from exc
        self.committed = True

    def __enter__(self) -> "SqlAuthUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self.committed:
                self.session.rollback()
        finally:
            self.session.close()


class SqlAuthStore:
    """Calling the store opens a new unit of work."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAuthUnitOfWork:
        return SqlAuthUnitOfWork(self._session_factory)
