"""Spike: does a router-level default guard with explicit per-route override hold against URL tricks?"""

import asyncio
import contextvars
import threading
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

PERMS: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar("perms", default=frozenset())


def require(pid: str) -> Any:
    def check() -> None:
        if pid not in PERMS.get():
            raise HTTPException(403, "denied")

    check.__netview_permission__ = pid  # type: ignore[attr-defined]
    return Depends(check)


def default_guard(plugin_id: str) -> Any:
    def guard(request: Request) -> None:
        route = request.scope.get("route")
        assert route is not None, "scope has no route"
        for dep in route.dependant.dependencies:
            if getattr(dep.call, "__netview_permission__", None):
                return
        suffix = "view" if request.method in ("GET", "HEAD", "OPTIONS") else "use"
        if f"{plugin_id}.{suffix}" not in PERMS.get():
            raise HTTPException(403, "denied")

    return Depends(guard)


SEEN_IN_SYNC: list[frozenset[str]] = []


def build(tmp_path: Any) -> FastAPI:
    r = APIRouter()

    @r.get("/data")
    def data() -> dict[str, str]:
        return {"secret": "x"}

    @r.get("/ports/{name:path}")
    def port(name: str) -> dict[str, str]:
        SEEN_IN_SYNC.append(PERMS.get())
        return {"port": name}

    @r.post("/poll")
    def poll() -> dict[str, bool]:
        return {"ok": True}

    @r.post("/console", dependencies=[require("demo.console")])
    def console() -> dict[str, bool]:
        return {"opened": True}

    app = FastAPI()

    class PermMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            hdr = dict(scope["headers"]).get(b"x-perms", b"").decode()
            token = PERMS.set(frozenset(p for p in hdr.split(",") if p))
            try:
                await self.app(scope, receive, send)
            finally:
                PERMS.reset(token)

    app.add_middleware(PermMiddleware)
    app.include_router(r, prefix="/api/v1/plugins/demo", dependencies=[default_guard("demo")])
    static = tmp_path / "static"
    static.mkdir()
    (static / "ui.js").write_text("export default 1")
    (tmp_path / "secret.txt").write_text("outside")
    app.mount("/plugins/demo/static", StaticFiles(directory=static), name="s")
    return app


@pytest.fixture
def client(tmp_path: Any) -> TestClient:
    return TestClient(build(tmp_path))


def h(*perms: str) -> dict[str, str]:
    return {"x-perms": ",".join(perms)}


def test_get_needs_view(client: TestClient) -> None:
    assert client.get("/api/v1/plugins/demo/data").status_code == 403
    assert client.get("/api/v1/plugins/demo/data", headers=h("demo.view")).status_code == 200


def test_post_needs_use(client: TestClient) -> None:
    assert client.post("/api/v1/plugins/demo/poll", headers=h("demo.view")).status_code == 403
    assert client.post("/api/v1/plugins/demo/poll", headers=h("demo.use")).status_code == 200


def test_explicit_overrides_default(client: TestClient) -> None:
    assert client.post("/api/v1/plugins/demo/console", headers=h("demo.use")).status_code == 403
    assert client.post("/api/v1/plugins/demo/console", headers=h("demo.console")).status_code == 200


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "PUT", "DELETE", "PATCH", "TRACE"])
def test_other_methods_never_leak(client: TestClient, method: str) -> None:
    r = client.request(method, "/api/v1/plugins/demo/data")
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
def test_path_tricks_never_leak(client: TestClient, path: str) -> None:
    r = client.get(path, follow_redirects=True)
    assert r.status_code in (401, 403, 404, 405), (path, r.status_code, r.text)


def test_encoded_slash_reaches_route_but_still_guarded(client: TestClient) -> None:
    r = client.get("/api/v1/plugins/demo/ports/1%2F0%2F5", headers=h("demo.view"))
    assert r.status_code == 200 and r.json() == {"port": "1/0/5"}


def test_contextvar_reaches_sync_route_in_threadpool(client: TestClient) -> None:
    SEEN_IN_SYNC.clear()
    client.get("/api/v1/plugins/demo/ports/1", headers=h("demo.view", "zzz"))
    assert SEEN_IN_SYNC == [frozenset({"demo.view", "zzz"})]


@pytest.mark.parametrize(
    "path",
    [
        "/plugins/demo/static/../secret.txt",
        "/plugins/demo/static/%2e%2e/secret.txt",
        "/plugins/demo/static/..%2fsecret.txt",
        "/plugins/demo/static/..%5csecret.txt",
    ],
)
def test_static_traversal_404(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 404 and b"outside" not in r.content, (path, r.status_code)


async def _raw(app: Any, method: str, path: str, raw: bytes, perms: str = "") -> tuple[int, bytes]:
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
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": raw, "root_path": "", "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"x-perms", perms.encode())],
        "client": ("127.0.0.1", 1), "server": ("localhost", 80),
    }
    await app(scope, receive, send)
    return status, body


@pytest.mark.parametrize(
    "path,raw",
    [
        ("/api/v1/plugins/demo/x/../data", b"/api/v1/plugins/demo/x/../data"),
        ("/api/v1/plugins/demo/./data", b"/api/v1/plugins/demo/./data"),
        ("/api/v1/plugins/x/../demo/data", b"/api/v1/plugins/x/../demo/data"),
        ("/plugins/demo/static/../secret.txt", b"/plugins/demo/static/../secret.txt"),
        ("/plugins/demo/static/../../secret.txt", b"/plugins/demo/static/%2e%2e/%2e%2e/secret.txt"),
        ("/plugins/demo/static/..\secret.txt", b"/plugins/demo/static/..%5csecret.txt"),
    ],
)
def test_raw_unnormalized_paths(tmp_path: Any, path: str, raw: bytes) -> None:
    status, body = asyncio.run(_raw(build(tmp_path), "GET", path, raw))
    assert status in (401, 403, 404, 405), (path, status, body)
    assert b"secret" not in body and b"outside" not in body
