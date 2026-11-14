"""Per-user dashboard layouts, and the administrator's default."""

import json
import logging
from dataclasses import dataclass
from typing import Literal

from netview.application.auth.principal import Principal
from netview.application.ports.auth_store import AuthStore, AuthUnitOfWork
from netview.application.ports.clock import Clock
from netview.domain.auth import ADMIN_ROLE
from netview.domain.dashboard import DashboardLayout, layout_to_json, parse_layout
from netview.domain.errors import NotFoundError, ValidationError

DEFAULT_KEY = "dashboard.default_layout"
PERMISSION = "core.dashboard"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoutView:
    layout: DashboardLayout | None
    source: Literal["user", "default", "builtin"]
    updated_ms: int | None
    default: DashboardLayout | None


@dataclass(frozen=True)
class DefaultView:
    layout: DashboardLayout | None
    users_with_own_layout: int
    roles_with_permission: list[str]


def _decode(raw: str, what: str) -> DashboardLayout | None:
    """A stored record that is corrupt or from another version counts as absent."""
    try:
        return parse_layout(json.loads(raw))
    except (ValueError, ValidationError):
        log.warning("ignoring a stored dashboard layout that cannot be read (%s)", what)
        return None


def _stored_default(uow: AuthUnitOfWork) -> DashboardLayout | None:
    raw = uow.settings.get(DEFAULT_KEY)
    return None if raw is None else _decode(raw, "default")


def _need_user(actor: Principal) -> int:
    if actor.user_id is None:
        raise ValidationError("Sign in to save a dashboard layout")
    return actor.user_id


class DashboardLayouts:
    def __init__(self, store: AuthStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    @staticmethod
    def _view(uow: AuthUnitOfWork, actor: Principal) -> LayoutView:
        default = _stored_default(uow)
        if actor.user_id is not None and actor.can(PERMISSION):
            stored = uow.layouts.get(actor.user_id)
            if stored is not None:
                own = _decode(stored.layout_json, f"user {actor.user_id}")
                if own is not None:
                    return LayoutView(own, "user", stored.updated_ms, default)
        if default is not None:
            return LayoutView(default, "default", None, default)
        return LayoutView(None, "builtin", None, None)

    def mine(self, actor: Principal) -> LayoutView:
        with self._store() as uow:
            return self._view(uow, actor)

    def save_mine(self, actor: Principal, layout: DashboardLayout) -> LayoutView:
        user_id = _need_user(actor)
        with self._store() as uow:
            if uow.users.get(user_id) is None:
                raise NotFoundError("Your account no longer exists")
            uow.layouts.put(user_id, layout_to_json(layout), self._clock.now_ms())
            uow.commit()
            return self._view(uow, actor)

    def reset_mine(self, actor: Principal) -> LayoutView:
        user_id = _need_user(actor)
        with self._store() as uow:
            uow.layouts.remove(user_id)
            uow.commit()
            return self._view(uow, actor)

    @staticmethod
    def _default_view(uow: AuthUnitOfWork) -> DefaultView:
        names = {role.name for role in uow.roles.list() if PERMISSION in role.permissions}
        admin = uow.roles.get(ADMIN_ROLE)
        names.add(admin.name if admin is not None else "Administrator")
        return DefaultView(_stored_default(uow), uow.layouts.count(), sorted(names))

    def default(self) -> DefaultView:
        with self._store() as uow:
            return self._default_view(uow)

    def save_default(self, actor: Principal, layout: DashboardLayout, *, clear_mine: bool) -> DefaultView:
        with self._store() as uow:
            uow.settings.set(DEFAULT_KEY, layout_to_json(layout))
            if clear_mine and actor.user_id is not None:
                uow.layouts.remove(actor.user_id)
            uow.commit()
            return self._default_view(uow)

    def reset_everyone(self) -> int:
        with self._store() as uow:
            removed = uow.layouts.remove_all()
            uow.commit()
            return removed
