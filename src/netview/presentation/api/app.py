"""FastAPI application factory."""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from functools import partial
from pathlib import Path

import swagger_ui_bundle
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from netview.application.plugins.ui import UiContribution
from netview.application.services import AppServices
from netview.domain.errors import NotFoundError
from netview.presentation.api.auth_middleware import AuthMiddleware
from netview.presentation.api.errors import register_error_handlers
from netview.presentation.api.permissions import plugin_default_guard
from netview.presentation.api.routers import (
    admin,
    auth,
    devices,
    events,
    inspections,
    metrics,
    plugins,
    scan,
    setup,
    state,
    stream,
    themes,
    watches,
)
from netview.presentation.api.security import SecurityMiddleware

WEB_STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
SWAGGER_DIR = Path(swagger_ui_bundle.swagger_ui_path)

_DOCS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NetView API</title>
<link rel="stylesheet" href="/static/swagger/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="/static/swagger/swagger-ui-bundle.js"></script>
<script src="/docs/init.js"></script>
</body>
</html>
"""

# An external script rather than the inline one FastAPI's helper emits: the CSP forbids inline scripts.
_DOCS_INIT_JS = (
    "window.ui = SwaggerUIBundle({url: '/openapi.json', dom_id: '#swagger-ui', "
    "presets: [SwaggerUIBundle.presets.apis], layout: 'BaseLayout'});\n"
)


NO_CACHE = {"Cache-Control": "no-cache"}
"""Revalidate on every load (a cheap 304 via the ETag): no stale module after an upgrade."""


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles whose responses, 304s included, carry ``Cache-Control: no-cache``."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


class PresentStaticFiles(NoCacheStaticFiles):
    """A plugin's static files, which answer 404 once the plugin is uninstalled (folder gone or not)."""

    def __init__(self, directory: str | Path, present: Callable[[], bool]) -> None:
        super().__init__(directory=directory)
        self.present = present

    async def check_config(self) -> None:
        if self.present():
            await super().check_config()

    async def get_response(self, path: str, scope: Scope) -> Response:
        if not self.present():
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


def plugin_present(source_id: str, present: Callable[[str], bool]) -> Callable[[], None]:
    """Route dependency: 404 once the plugin is uninstalled. It runs before the permission guard."""

    def check() -> None:
        if not present(source_id):
            raise NotFoundError(f"unknown plugin {source_id!r}")

    return check


class _OptionalStaticFiles(NoCacheStaticFiles):
    """Static files from a folder that may not exist (or vanish while running): 404, never a 500."""

    async def check_config(self) -> None:
        return None  # StaticFiles would raise on a missing directory; lookups then simply find nothing


_CORE_ROUTERS = (state, devices, watches, scan, inspections, events, metrics, plugins, stream, themes)


def create_app(
    services: AppServices,
    routers: list[tuple[str, APIRouter]],
    ui: list[tuple[str, UiContribution]],
    allowed_hosts: set[str],
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    guids: Mapping[str, str] | None = None,
    present: Callable[[str], bool] | None = None,
) -> FastAPI:
    """``routers`` and ``ui`` are keyed by ``str(source_id)``; ``guids`` maps each of those keys to its guid.

    Permissions are checked against the guid. Without ``guids`` a key is taken to be its own guid.
    ``present(key)`` is false once that plugin is uninstalled: its routes and static files then answer 404
    for everyone, and the auth middleware no longer knows its guid, so it never answers 403 for it.
    """
    is_present = present or (lambda _key: True)
    app = FastAPI(title="NetView", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.services = services
    plugin_guids: dict[str, str] = {key: key for key, _ in [*routers, *ui]}
    plugin_guids.update(guids or {})
    app.add_middleware(
        AuthMiddleware,
        services=services,
        plugin_guids=lambda: {k: g for k, g in plugin_guids.items() if is_present(k)},
    )
    app.add_middleware(SecurityMiddleware, allowed_hosts=allowed_hosts)
    register_error_handlers(app)

    for module in _CORE_ROUTERS:
        app.include_router(module.router, prefix="/api/v1")
    if services.auth is not None:
        for module in (auth, setup, admin):
            app.include_router(module.router, prefix="/api/v1")
    for plugin_id, router in routers:
        app.include_router(
            router,
            prefix=f"/api/v1/plugins/{plugin_id}",
            dependencies=[
                Depends(plugin_present(plugin_id, is_present)),
                Depends(plugin_default_guard(plugin_guids[plugin_id])),
            ],
        )
    for plugin_id, contribution in ui:
        app.mount(
            f"/plugins/{plugin_id}/static",
            PresentStaticFiles(contribution.static_dir, partial(is_present, plugin_id)),
            name=f"plugin-static-{plugin_id}",
        )

    @app.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        return HTMLResponse(_DOCS_HTML)

    @app.get("/docs/init.js", include_in_schema=False)
    def docs_init() -> Response:
        return Response(_DOCS_INIT_JS, media_type="text/javascript", headers=NO_CACHE)

    @app.get("/login", include_in_schema=False)
    def login_page() -> FileResponse:
        return FileResponse(WEB_STATIC / "login.html", headers=NO_CACHE)

    @app.get("/setup", include_in_schema=False)
    def setup_page() -> FileResponse:
        return FileResponse(WEB_STATIC / "setup.html", headers=NO_CACHE)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_STATIC / "index.html", headers=NO_CACHE)

    app.mount(
        "/themes/user",
        _OptionalStaticFiles(directory=services.themes.user_dir(), check_dir=False),
        name="user-themes",
    )
    app.mount("/static/swagger", NoCacheStaticFiles(directory=SWAGGER_DIR), name="swagger")
    app.mount("/static", NoCacheStaticFiles(directory=WEB_STATIC), name="static")
    return app
