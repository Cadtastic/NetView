"""The signed-in caller, and the context variable that carries it through a request."""

from contextvars import ContextVar
from dataclasses import dataclass

from netview.domain.auth import PermissionSet


@dataclass(frozen=True)
class Principal:
    user_id: int | None
    username: str
    display_name: str
    provider: str
    permissions: PermissionSet
    must_change_password: bool = False

    def can(self, permission_id: str) -> bool:
        return self.permissions.has(permission_id)


SYSTEM_PRINCIPAL = Principal(
    user_id=None,
    username="system",
    display_name="System",
    provider="system",
    permissions=PermissionSet(everything=True, ids=frozenset()),
)

current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


def get_principal() -> Principal | None:
    return current_principal.get()
