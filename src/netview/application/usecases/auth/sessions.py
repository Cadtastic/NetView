"""Sessions and permission resolution."""

import hashlib
import secrets
import threading
from collections.abc import Callable

from netview.application.auth.principal import Principal
from netview.application.ports.auth_store import AuthStore, SessionRecord
from netview.application.ports.clock import Clock
from netview.domain.auth import AuthPolicy, PermissionSet, User, resolve_permissions


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Authorizer:
    """Resolves a user's permissions from their roles, cached per user until ``invalidate``."""

    def __init__(self, store: AuthStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._cache: dict[tuple[int, frozenset[str]], PermissionSet] = {}

    def permissions(self, user: User) -> PermissionSet:
        key = (user.id, user.role_ids)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        with self._store() as uow:
            roles = [r for r in (uow.roles.get(rid) for rid in sorted(user.role_ids)) if r is not None]
        resolved = resolve_permissions(roles)
        with self._lock:
            self._cache[key] = resolved
        return resolved

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()


class SessionService:
    def __init__(
        self,
        store: AuthStore,
        clock: Clock,
        authorizer: Authorizer,
        policy: Callable[[], AuthPolicy],
    ) -> None:
        self._store = store
        self._clock = clock
        self._authorizer = authorizer
        self._policy = policy

    def principal_for(self, user: User) -> Principal:
        return Principal(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            provider=user.provider,
            permissions=self._authorizer.permissions(user),
            must_change_password=user.must_change_password,
        )

    def create(self, user_id: int, ip: str, user_agent: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock.now_ms()
        with self._store() as uow:
            uow.sessions.add(SessionRecord(hash_token(token), user_id, now, now, ip, user_agent))
            uow.commit()
        return token

    def resolve(self, token: str) -> Principal | None:
        digest = hash_token(token)
        now = self._clock.now_ms()
        policy = self._policy()
        with self._store() as uow:
            record = uow.sessions.get(digest)
            if record is None:
                return None
            idle = now - record.last_seen_ms > policy.session_idle_s * 1000
            too_old = now - record.created_ms > policy.session_max_s * 1000
            if idle or too_old:
                uow.sessions.remove(digest)
                uow.commit()
                return None
            user = uow.users.get(record.user_id)
            if user is None or not user.enabled:
                return None
            uow.sessions.touch(digest, now)
            uow.commit()
        return self.principal_for(user)

    def end(self, token: str) -> None:
        with self._store() as uow:
            uow.sessions.remove(hash_token(token))
            uow.commit()

    def end_all(self, user_id: int) -> None:
        with self._store() as uow:
            uow.sessions.remove_for_user(user_id)
            uow.commit()

    def end_others(self, user_id: int, keep_token: str) -> None:
        """End every session of the user except the one for ``keep_token``."""
        with self._store() as uow:
            keep = uow.sessions.get(hash_token(keep_token))
            uow.sessions.remove_for_user(user_id)
            if keep is not None and keep.user_id == user_id:
                uow.sessions.add(keep)
            uow.commit()
