"""Users, roles, permissions and the rules for usernames and passwords."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from netview.domain.errors import ValidationError

ADMIN_ROLE = "administrator"
DEFAULT_ROLE = "default"
BUILTIN_ROLES = frozenset({ADMIN_ROLE, DEFAULT_ROLE})

_USERNAME = re.compile(r"[a-z0-9._@+-]{1,128}")


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    builtin: bool
    permissions: frozenset[str]


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    email: str | None
    enabled: bool
    builtin: bool
    must_change_password: bool
    role_ids: frozenset[str]
    provider: str
    created_ms: int
    last_sign_in_ms: int | None
    security_version: int = 0
    """Bumped when the password changes; sessions from an older version stop working."""


@dataclass(frozen=True)
class PermissionSet:
    everything: bool
    ids: frozenset[str]

    def has(self, permission_id: str) -> bool:
        return self.everything or permission_id in self.ids

    def as_list(self, catalog_ids: Iterable[str]) -> list[str]:
        if self.everything:
            return sorted(catalog_ids)
        return sorted(self.ids)


def resolve_permissions(roles: Iterable[Role]) -> PermissionSet:
    everything = False
    ids: set[str] = set()
    for role in roles:
        if role.id == ADMIN_ROLE:
            everything = True
        ids |= role.permissions
    return PermissionSet(everything, frozenset(ids))


def normalize_username(raw: str) -> str:
    name = unicodedata.normalize("NFKC", raw).strip().casefold()
    if not _USERNAME.fullmatch(name):
        raise ValidationError(fields={"username": "Use letters, digits and . _ @ + - only"})
    return name


@dataclass(frozen=True)
class AuthPolicy:
    password_min_length: int = 12
    session_idle_s: int = 28800
    session_max_s: int = 604800
    lockout_failures: int = 5
    lockout_window_s: int = 900
    lockout_s: int = 900

    def validate(self) -> None:
        fields: dict[str, str] = {}
        if self.password_min_length < 8:
            fields["password_min_length"] = "Must be at least 8"
        for name in ("session_idle_s", "session_max_s", "lockout_failures", "lockout_window_s", "lockout_s"):
            if getattr(self, name) < 1:
                fields[name] = "Must be at least 1"
        if fields:
            raise ValidationError(fields=fields)


def check_password(password: str, username: str, min_length: int) -> None:
    if len(password) < min_length:
        raise ValidationError(fields={"password": f"Use at least {min_length} characters"})
    if password.casefold() == username.casefold():
        raise ValidationError(fields={"password": "Must not be the same as the username"})
