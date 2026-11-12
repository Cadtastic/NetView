"""Who may do what: the guards that routes attach with ``dependencies=[require_permission(...)]``."""

from typing import Annotated, Any

from fastapi import Depends, Request

from netview.application.auth.catalog import default_permission_for
from netview.application.auth.principal import SYSTEM_PRINCIPAL, Principal, get_principal
from netview.domain.errors import AuthenticationError, PermissionDeniedError


def current_user(request: Request) -> Principal:
    """The caller. Without sign-in wired in (``services.auth is None``) every caller is the system."""
    principal = get_principal()
    if principal is not None:
        return principal
    if request.app.state.services.auth is None:
        return SYSTEM_PRINCIPAL
    raise AuthenticationError("sign in required")


CurrentUser = Annotated[Principal, Depends(current_user)]


def require_permission(permission_id: str) -> Any:
    def check(request: Request) -> None:
        if not current_user(request).can(permission_id):
            raise PermissionDeniedError("You do not have permission to do that")

    # Read by the default guard of plugin routers (Task 9): a route with an explicit guard keeps it.
    check.__netview_permission__ = permission_id  # type: ignore[attr-defined]
    return Depends(check)


def require_admin() -> Any:
    def check(request: Request) -> None:
        if not current_user(request).permissions.everything:
            raise PermissionDeniedError("Administrator only")

    check.__netview_permission__ = "core.admin"  # type: ignore[attr-defined]
    return Depends(check)


def explicit_permission(call: object) -> str | None:
    """The permission an explicit route guard declares, or None when ``call`` is not one."""
    permission = getattr(call, "__netview_permission__", None)
    return permission if isinstance(permission, str) and permission else None


def plugin_default_guard(plugin_id: str) -> Any:
    """Router-level guard for a plugin's routes: ``<id>.view`` to read, ``<id>.use`` to change.

    A route that carries its own guard (``require_permission`` or ``ctx.require``) is left to that
    guard. A request that reached no route fails closed.
    """

    def guard(request: Request) -> None:
        route = request.scope.get("route")
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            raise PermissionDeniedError("You do not have permission to do that")
        if any(explicit_permission(dep.call) for dep in dependant.dependencies):
            return
        if not current_user(request).can(default_permission_for(plugin_id, request.method)):
            raise PermissionDeniedError("You do not have permission to do that")

    return guard
