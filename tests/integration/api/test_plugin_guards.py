"""Plugin routes are guarded by default; an explicit ``ctx.require`` replaces the default (Review Focus 1)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import ApiWorld, make_app, make_client
from fastapi import APIRouter
from fastapi.testclient import TestClient

from netview.application.plugins.ui import UiContribution
from netview.application.ports.audit import AuditEntry
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk import UserPermission
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
    RecordingEventBus,
)


class Recorder:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


@pytest.fixture
def sink() -> Recorder:
    return Recorder()


@pytest.fixture
def ctx(tmp_path: Path, sink: Recorder) -> Iterator[DefaultPluginContext]:
    context = DefaultPluginContext(
        "demo",
        None,
        make_engine(f"sqlite:///{tmp_path / 'p.db'}"),
        FakeClock(),
        FakeNetworkTools(),
        FakeVendors(),
        InMemoryMetrics(),
        None,  # type: ignore[arg-type]
        RecordingEventBus(),
        FakeServiceProbes(),
        FakeSystemInfo(),
        FakeSnmpClient([]),
        audit_sink=sink,
    )
    yield context
    context.close()


@pytest.fixture
def world(world: ApiWorld) -> ApiWorld:
    info = world.admin.plugins["demo"]
    info.capabilities = ["api", "web_ui"]
    info.user_permissions = [UserPermission("console", "Open the console")]
    return world


def build_router(ctx: DefaultPluginContext) -> APIRouter:
    router = APIRouter()

    @router.get("/data")
    def data() -> dict[str, str]:
        return {"secret": "x"}

    @router.get("/ports/{name:path}")
    def port(name: str) -> dict[str, str]:
        return {"port": name, "caller": ctx.principal().username}

    @router.post("/poll")
    def poll() -> dict[str, bool]:
        return {"ok": True}

    @router.post("/console", dependencies=[ctx.require("console")])
    def console() -> dict[str, bool]:
        ctx.audit("console.open", target="sw1")
        return {"opened": True}

    return router


@pytest.fixture
def app_parts(world: ApiWorld, ctx: DefaultPluginContext, tmp_path: Path) -> Any:
    static = tmp_path / "static"
    static.mkdir()
    (static / "ui.js").write_text("export default 1")
    (tmp_path / "secret.txt").write_text("outside")
    world.add_user("plain")  # Default: core.view only
    world.grant("viewer", "demo.view")
    world.grant("user", "demo.use")
    world.grant("console", "demo.console")
    return make_app(world, [("demo", build_router(ctx))], [("demo", UiContribution(static))])


def client_for(app: Any, user: str | None) -> TestClient:
    return make_client(app, user=user)


def test_plugin_get_needs_view_post_needs_use(app_parts: Any) -> None:
    viewer = client_for(app_parts, "viewer")
    user = client_for(app_parts, "user")

    assert viewer.get("/api/v1/plugins/demo/data").status_code == 200
    assert user.get("/api/v1/plugins/demo/data").status_code == 403
    assert viewer.post("/api/v1/plugins/demo/poll").status_code == 403
    assert user.post("/api/v1/plugins/demo/poll").status_code == 200
    assert client_for(app_parts, "plain").get("/api/v1/plugins/demo/data").status_code == 403
    assert client_for(app_parts, None).get("/api/v1/plugins/demo/data").status_code == 401
    assert client_for(app_parts, "admin").post("/api/v1/plugins/demo/poll").status_code == 200


def test_explicit_guard_overrides_default(app_parts: Any) -> None:
    only_console = client_for(app_parts, "console")
    only_use = client_for(app_parts, "user")

    assert only_console.post("/api/v1/plugins/demo/console").status_code == 200
    assert only_use.post("/api/v1/plugins/demo/console").status_code == 403


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "PUT", "DELETE", "PATCH", "TRACE"])
@pytest.mark.parametrize("user", [None, "plain"])
def test_other_methods_never_leak(app_parts: Any, method: str, user: str | None) -> None:
    r = client_for(app_parts, user).request(method, "/api/v1/plugins/demo/data")
    assert r.status_code in (401, 403, 404, 405), (method, r.status_code)
    assert b"secret" not in r.content


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/plugins/demo/data/",
        "/api/v1/plugins/demo//data",
        "/api/v1/plugins/demo/./data",
        "/api/v1/plugins/demo/x/../data",
        "/api/v1/plugins/Demo/data",
        "/api/v1/plugins/demo/%64ata",
        "/api/v1/plugins/demo/ports/1%2F0%2F5",
    ],
)
@pytest.mark.parametrize("user", [None, "plain"])
def test_guard_holds_against_url_tricks(app_parts: Any, path: str, user: str | None) -> None:
    r = client_for(app_parts, user).get(path, follow_redirects=True)
    assert r.status_code in (401, 403, 404, 405), (path, r.status_code, r.text)
    assert b"secret" not in r.content and b'"port"' not in r.content


def test_encoded_slash_reaches_route_but_still_guarded(app_parts: Any) -> None:
    path = "/api/v1/plugins/demo/ports/1%2F0%2F5"
    assert client_for(app_parts, "plain").get(path).status_code == 403
    r = client_for(app_parts, "viewer").get(path)
    assert r.status_code == 200 and r.json()["port"] == "1/0/5"


def test_principal_reaches_sync_route_in_threadpool(app_parts: Any) -> None:
    r = client_for(app_parts, "viewer").get("/api/v1/plugins/demo/ports/1")
    assert r.json()["caller"] == "viewer"


@pytest.mark.parametrize(
    "path",
    [
        "/plugins/demo/static/../secret.txt",
        "/plugins/demo/static/%2e%2e/secret.txt",
        "/plugins/demo/static/..%2fsecret.txt",
        "/plugins/demo/static/..%5csecret.txt",
    ],
)
def test_static_traversal_404(app_parts: Any, path: str) -> None:
    r = client_for(app_parts, "viewer").get(path)
    assert r.status_code == 404 and b"outside" not in r.content, (path, r.status_code)


def test_static_needs_view(app_parts: Any) -> None:
    assert client_for(app_parts, "viewer").get("/plugins/demo/static/ui.js").status_code == 200
    assert client_for(app_parts, "plain").get("/plugins/demo/static/ui.js").status_code == 403
    assert client_for(app_parts, "user").get("/plugins/demo/static/ui.js").status_code == 403
    assert client_for(app_parts, "admin").get("/plugins/demo/static/ui.js").status_code == 200


async def _raw(app: Any, method: str, path: str, raw: bytes, cookie: str) -> tuple[int, bytes]:
    status = 0
    body = b""

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        nonlocal status, body
        if msg["type"] == "http.response.start":
            status = msg["status"]
        elif msg["type"] == "http.response.body":
            body += msg.get("body", b"")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": raw,
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"localhost"),
            (b"x-netview", b"1"),
            (b"cookie", f"netview_session={cookie}".encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("localhost", 80),
    }
    await app(scope, receive, send)
    return status, body


@pytest.mark.parametrize(
    ("path", "raw"),
    [
        ("/api/v1/plugins/demo/x/../data", b"/api/v1/plugins/demo/x/../data"),
        ("/api/v1/plugins/demo/./data", b"/api/v1/plugins/demo/./data"),
        ("/api/v1/plugins/x/../demo/data", b"/api/v1/plugins/x/../demo/data"),
        ("/plugins/demo/static/../secret.txt", b"/plugins/demo/static/../secret.txt"),
        ("/plugins/demo/static/../../secret.txt", b"/plugins/demo/static/%2e%2e/%2e%2e/secret.txt"),
        ("/plugins/demo/static/..\\secret.txt", b"/plugins/demo/static/..%5csecret.txt"),
    ],
)
@pytest.mark.parametrize("user", ["plain", "viewer"])
def test_raw_unnormalized_paths(app_parts: Any, path: str, raw: bytes, user: str) -> None:
    auth = app_parts.state.services.auth
    found = next(u for u in auth.users.list() if u.username == user)
    token = auth.sessions.create(found.id, "testclient", "pytest")
    status, body = asyncio.run(_raw(app_parts, "GET", path, raw, token))
    assert status in (401, 403, 404, 405), (path, status, body)
    assert b"secret" not in body and b"outside" not in body


def test_disabled_plugin_permissions_listed_off(world: ApiWorld, app_parts: Any) -> None:
    world.admin.plugins["demo"].state = "disabled"
    r = client_for(app_parts, "admin").get("/api/v1/admin/permissions")

    assert r.status_code == 200
    group = next(g for g in r.json() if g["owner"] == "demo")
    assert group["off"] is True
    assert {"demo.view", "demo.use", "demo.console"} <= {p["id"] for p in group["permissions"]}


def test_ctx_audit_reaches_sink_with_caller(app_parts: Any, sink: Recorder) -> None:
    assert client_for(app_parts, "console").post("/api/v1/plugins/demo/console").status_code == 200

    assert [(e.username, e.action, e.target, e.outcome) for e in sink.entries] == [
        ("console", "console.open", "sw1", "ok")
    ]
