"""Authentication as pure ASGI: who is this, and may they reach this path at all."""

import re
from collections.abc import Callable, Mapping
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from netview.application.auth.principal import Principal, current_principal
from netview.application.services import AppServices
from netview.presentation.api.deps import SESSION_COOKIE
from netview.presentation.api.security import ASGIApp, Receive, Scope, Send

PUBLIC_EXACT = frozenset({"/login", "/setup", "/api/v1/auth/login", "/api/v1/auth/providers", "/favicon.ico"})
PUBLIC_PREFIXES = ("/static/", "/themes/user/")
SETUP_API = "/api/v1/setup"
DOCS_PATHS = frozenset({"/docs", "/docs/init.js", "/openapi.json"})
PASSWORD_CHANGE_OK = frozenset({"/api/v1/auth/me", "/api/v1/auth/password", "/api/v1/auth/logout"})
_PLUGIN_STATIC = re.compile(r"^/plugins/([^/]+)/static(/|$)")
_READ = ("GET", "HEAD")


def _is_public(path: str, setup_open: bool) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES) or (setup_open and path == SETUP_API)


def _is_api(path: str) -> bool:
    return path.startswith("/api/") or path == "/openapi.json"


class AuthMiddleware:
    def __init__(
        self, app: ASGIApp, services: AppServices, plugin_guids: Callable[[], Mapping[str, str]]
    ) -> None:
        self.app = app
        self.services = services
        self.plugin_guids = plugin_guids  # str(source_id) -> guid

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        auth = self.services.auth
        if scope["type"] != "http" or auth is None:
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        method: str = scope["method"]

        token = Request(scope).cookies.get(SESSION_COOKIE)
        principal: Principal | None = None
        if token:
            principal = await run_in_threadpool(auth.sessions.resolve, token)
        # A principal means users exist, so setup is closed: only look when nobody is signed in.
        setup_open = principal is None and (await run_in_threadpool(auth.setup.status)).open

        denial = self._gate(scope, path, method, principal, setup_open)
        if denial is not None:
            await denial(scope, receive, send)
            return

        scope.setdefault("state", {})["principal"] = principal
        reset = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(reset)

    def _gate(
        self, scope: Scope, path: str, method: str, principal: Principal | None, setup_open: bool
    ) -> Response | None:
        if setup_open:
            if path == "/login":
                return RedirectResponse("/setup", status_code=303)
            if not _is_public(path, True):
                if method in _READ and not _is_api(path):
                    return RedirectResponse("/setup", status_code=303)
                return JSONResponse({"error": "setup required"}, status_code=409)
            return None

        if principal is None:
            if _is_public(path, False):
                return None
            if _is_api(path) or method not in _READ:
                return JSONResponse({"error": "sign in required"}, status_code=401)
            target = path + (
                f"?{scope['query_string'].decode('latin-1')}" if scope.get("query_string") else ""
            )
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)

        if principal.must_change_password and path.startswith("/api/") and path not in PASSWORD_CHANGE_OK:
            return JSONResponse({"error": "password change required"}, status_code=403)
        if path in DOCS_PATHS and not principal.can("core.view"):
            return JSONResponse({"error": "permission denied"}, status_code=403)
        match = _PLUGIN_STATIC.match(path)
        if match:
            # an address carries the source_id; permissions are held on the guid. An unknown source_id goes on
            # to routing, which answers 404.
            guid = self.plugin_guids().get(match.group(1))
            if guid is not None and not principal.can(f"{guid}.view"):
                return JSONResponse({"error": "permission denied"}, status_code=403)
        return None
