"""User, role and policy administration."""

import re
from collections.abc import Callable
from dataclasses import dataclass, fields, replace

from netview.application.auth.catalog import ADMIN_ONLY, PermissionGroup, catalog_ids
from netview.application.ports.auth_store import AuthStore
from netview.application.ports.clock import Clock
from netview.application.ports.password_hasher import PasswordHasher
from netview.application.usecases.auth.sessions import Authorizer, SessionService
from netview.domain.auth import ADMIN_ROLE, AuthPolicy, Role, User, check_password, normalize_username
from netview.domain.errors import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class RoleView:
    role: Role
    user_count: int


class UserAdmin:
    def __init__(
        self,
        store: AuthStore,
        hasher: PasswordHasher,
        sessions: SessionService,
        authorizer: Authorizer,
        policy: Callable[[], AuthPolicy],
        clock: Clock,
    ) -> None:
        self._store = store
        self._hasher = hasher
        self._sessions = sessions
        self._authorizer = authorizer
        self._policy = policy
        self._clock = clock

    def list(self) -> list[User]:
        with self._store() as uow:
            return uow.users.list()

    def create_local(self, username: str, display_name: str, password: str, role_ids: set[str]) -> User:
        name = normalize_username(username)
        check_password(password, name, self._policy().password_min_length)
        with self._store() as uow:
            self._require_roles(uow.roles.get, role_ids)
            user = User(
                id=0,
                username=name,
                display_name=display_name.strip() or name,
                email=None,
                enabled=True,
                builtin=False,
                must_change_password=True,
                role_ids=frozenset(role_ids),
                provider="local",
                created_ms=self._clock.now_ms(),
                last_sign_in_ms=None,
            )
            created = uow.users.add(user, self._hasher.hash(password))
            uow.commit()
        return created

    def update(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        role_ids: set[str] | None = None,
        enabled: bool | None = None,
    ) -> User:
        with self._store() as uow:
            user = uow.users.get(user_id)
            if user is None:
                raise NotFoundError("user not found")
            if user.builtin:
                if enabled is False:
                    raise ValidationError("The built-in administrator cannot be disabled")
                if role_ids is not None and ADMIN_ROLE not in role_ids:
                    raise ValidationError("The built-in administrator must keep the Administrator role")
            if role_ids is not None:
                self._require_roles(uow.roles.get, role_ids)
            changed = replace(
                user,
                display_name=user.display_name
                if display_name is None
                else display_name.strip() or user.username,
                role_ids=user.role_ids if role_ids is None else frozenset(role_ids),
                enabled=user.enabled if enabled is None else enabled,
            )
            uow.users.save(changed)
            uow.commit()
        if user.enabled and not changed.enabled:
            self._sessions.end_all(user_id)
        if changed.role_ids != user.role_ids:
            self._authorizer.invalidate()
        return changed

    def reset_password(self, user_id: int, password: str) -> None:
        policy = self._policy()
        with self._store() as uow:
            user = uow.users.get(user_id)
            if user is None:
                raise NotFoundError("user not found")
            check_password(password, user.username, policy.password_min_length)
            uow.users.set_password_hash(user_id, self._hasher.hash(password))
            uow.users.save(replace(user, must_change_password=True))
            uow.commit()
        self._sessions.end_all(user_id)

    def delete(self, user_id: int) -> None:
        with self._store() as uow:
            user = uow.users.get(user_id)
            if user is None:
                raise NotFoundError("user not found")
            if user.builtin:
                raise ValidationError("The built-in administrator cannot be deleted")
            uow.users.remove(user_id)
            uow.commit()
        self._sessions.end_all(user_id)

    @staticmethod
    def _require_roles(get: Callable[[str], Role | None], role_ids: set[str]) -> None:
        unknown = sorted(r for r in role_ids if get(r) is None)
        if unknown:
            raise ValidationError(fields={"roles": f"Unknown role: {', '.join(unknown)}"})


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


class RoleAdmin:
    def __init__(
        self,
        store: AuthStore,
        authorizer: Authorizer,
        catalog: Callable[[], list[PermissionGroup]],
    ) -> None:
        self._store = store
        self._authorizer = authorizer
        self._catalog = catalog

    def list(self) -> list[RoleView]:
        with self._store() as uow:
            users = uow.users.list()
            return [
                RoleView(role, sum(1 for u in users if role.id in u.role_ids)) for role in uow.roles.list()
            ]

    def create(self, name: str) -> Role:
        clean = name.strip()
        role_id = _slug(clean)
        if not role_id:
            raise ValidationError(fields={"name": "Enter a name"})
        with self._store() as uow:
            if uow.roles.get(role_id) is not None:
                raise ConflictError("a role with that name already exists")
            role = Role(role_id, clean, False, frozenset())
            uow.roles.add(role)
            uow.commit()
        return role

    def update(self, role_id: str, *, name: str | None = None, permissions: set[str] | None = None) -> Role:
        known = catalog_ids(self._catalog())
        with self._store() as uow:
            role = uow.roles.get(role_id)
            if role is None:
                raise NotFoundError("role not found")
            if name is not None and name.strip() != role.name:
                if role.builtin:
                    raise ValidationError("Built-in roles cannot be renamed")
                if not name.strip():
                    raise ValidationError(fields={"name": "Enter a name"})
            granted = role.permissions
            if permissions is not None:
                if role.id == ADMIN_ROLE:
                    raise ValidationError("The Administrator role always has every permission")
                locked = sorted(p for p in permissions if p in ADMIN_ONLY)
                if locked:
                    raise ValidationError(fields={"permissions": f"Administrator only: {', '.join(locked)}"})
                unknown = sorted(p for p in permissions if p not in known and p not in role.permissions)
                if unknown:
                    raise ValidationError(fields={"permissions": f"Unknown permission: {', '.join(unknown)}"})
                # Permissions of an uninstalled plugin cannot be shown, so they survive an edit.
                granted = frozenset(permissions) | (role.permissions - known)
            changed = replace(
                role,
                name=role.name if name is None or role.builtin else name.strip(),
                permissions=granted,
            )
            uow.roles.save(changed)
            uow.commit()
        self._authorizer.invalidate()
        return changed

    def delete(self, role_id: str) -> None:
        with self._store() as uow:
            role = uow.roles.get(role_id)
            if role is None:
                raise NotFoundError("role not found")
            if role.builtin:
                raise ValidationError("Built-in roles cannot be deleted")
            uow.roles.remove(role_id)
            uow.commit()
        self._authorizer.invalidate()


_POLICY_FIELDS = {f.name for f in fields(AuthPolicy)}


class PolicyAdmin:
    def __init__(self, store: AuthStore) -> None:
        self._store = store

    def get(self) -> AuthPolicy:
        defaults = AuthPolicy()
        values: dict[str, int] = {}
        with self._store() as uow:
            for name in _POLICY_FIELDS:
                raw = uow.settings.get(f"policy.{name}")
                if raw is not None:
                    try:
                        values[name] = int(raw)
                    except ValueError:
                        values[name] = getattr(defaults, name)
        return replace(defaults, **values)

    def update(self, **changes: int) -> AuthPolicy:
        unknown = sorted(set(changes) - _POLICY_FIELDS)
        if unknown:
            raise ValidationError(fields={n: "Unknown setting" for n in unknown})
        updated = replace(self.get(), **changes)
        updated.validate()
        with self._store() as uow:
            for name, value in changes.items():
                uow.settings.set(f"policy.{name}", str(value))
            uow.commit()
        return updated
