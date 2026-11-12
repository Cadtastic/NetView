import threading
import time
from urllib.parse import quote

import pytest
from api_helpers import PASSWORD, ApiWorld, build_world, make_app, make_client
from fastapi.testclient import TestClient

from netview.application.auth.principal import SYSTEM_PRINCIPAL
from netview.presentation.api.routers import stream as stream_module


def login(client: TestClient, username: str = "admin", password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_anonymous_api_401_and_page_redirects_to_login_with_next(world: ApiWorld) -> None:
    anon = make_client(make_app(world), user=None)
    response = anon.get("/api/v1/state")
    assert response.status_code == 401
    assert response.json() == {"error": "sign in required"}
    assert anon.get("/openapi.json").status_code == 401
    page = anon.get("/docs?x=1&y=a%20b", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/login?next=" + quote("/docs?x=1&y=a%20b", safe="")
    assert anon.get("/", follow_redirects=False).headers["location"] == "/login?next=%2F"
    assert anon.post("/api/v1/scan").status_code == 401


def test_public_paths_need_no_sign_in(world: ApiWorld) -> None:
    anon = make_client(make_app(world), user=None)
    assert anon.get("/api/v1/auth/me").status_code == 401
    providers = anon.get("/api/v1/auth/providers")
    assert providers.status_code == 200
    assert providers.json() == []
    assert anon.get("/static/js/main.js").status_code == 200
    assert anon.get("/themes/user/none.css").status_code == 404  # reached the mount, not the gate
    assert anon.get("/login", follow_redirects=False).status_code != 303


def test_login_sets_httponly_samesite_cookie_and_logout_clears(world: ApiWorld) -> None:
    client = make_client(make_app(world), user=None)
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
    assert body["is_admin"] is True
    assert "core.view" in body["permissions"]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("netview_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie
    assert client.get("/api/v1/auth/me").json()["username"] == "admin"

    out = client.post("/api/v1/auth/logout")
    assert out.status_code == 204
    assert "netview_session=" in out.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_cookie_is_secure_over_https(world: ApiWorld) -> None:
    client = TestClient(make_app(world), base_url="https://localhost", headers={"X-Netview": "1"})
    assert "Secure" in login(client).headers["set-cookie"]


def test_wrong_password_is_generic_401(world: ApiWorld) -> None:
    client = make_client(make_app(world), user=None)
    for name in ("admin", "nobody"):
        response = login(client, name, "wrong password!!")
        assert response.status_code == 401
        assert response.json() == {"error": "Username or password is wrong"}
    assert "set-cookie" not in response.headers


def test_login_lockout_returns_429(world: ApiWorld) -> None:
    client = make_client(make_app(world), user=None)
    for _ in range(5):
        assert login(client, "admin", "wrong password!!").status_code == 401
    locked = login(client)
    assert locked.status_code == 429
    assert locked.json() == {"error": "Too many attempts. Try again later."}


def test_login_requires_x_netview_header(world: ApiWorld) -> None:
    bare = make_client(make_app(world), with_header=False, user=None)
    assert login(bare).status_code == 403


def test_me_lists_permissions_of_the_signed_in_user(world: ApiWorld) -> None:
    world.add_user("kdoe")
    body = make_client(make_app(world), user="kdoe").get("/api/v1/auth/me").json()
    assert body == {
        "username": "kdoe",
        "display_name": "kdoe",
        "provider": "local",
        "must_change_password": False,
        "permissions": ["core.view"],
        "is_admin": False,
        "password_min_length": 12,
    }
    assert make_client(make_app(world)).get("/api/v1/auth/providers").json() == []


def test_must_change_password_blocks_other_api(world: ApiWorld) -> None:
    world.auth.users.create_local(SYSTEM_PRINCIPAL, "newbie", "", PASSWORD, {"default"})
    client = make_client(make_app(world), user=None)
    assert login(client, "newbie").json()["must_change_password"] is True
    blocked = client.get("/api/v1/state")
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "password change required"}
    assert client.get("/api/v1/auth/me").status_code == 200
    assert (
        client.post("/api/v1/auth/password", json={"current": "nope nope nope", "new": "x"}).status_code
        == 401
    )
    changed = client.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "a brand new password"})
    assert changed.status_code == 204
    assert client.get("/api/v1/state").status_code == 200


def test_disabled_user_next_request_401(world: ApiWorld) -> None:
    world.add_user("kdoe")
    client = make_client(make_app(world), user="kdoe")
    assert client.get("/api/v1/state").status_code == 200
    kdoe = next(u for u in world.auth.users.list() if u.username == "kdoe")
    world.auth.users.update(SYSTEM_PRINCIPAL, kdoe.id, enabled=False)
    assert client.get("/api/v1/state").status_code == 401


def test_role_change_applies_to_the_next_request(world: ApiWorld) -> None:
    world.add_user("kdoe")
    client = make_client(make_app(world))
    kdoe_client = make_client(make_app(world), user="kdoe")
    assert kdoe_client.get("/api/v1/state").status_code == 200
    world.auth.roles.update(SYSTEM_PRINCIPAL, "default", permissions=set())
    assert kdoe_client.get("/api/v1/state").status_code == 403
    assert client.get("/api/v1/state").status_code == 200


def test_stream_closes_after_session_ended(world: ApiWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_module, "KEEP_ALIVE_S", 0.05)
    token = world.session_token()
    client = TestClient(
        make_app(world),
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies={"netview_session": token},
    )
    ended = threading.Event()
    chunks: list[bytes] = []

    def reader() -> None:
        with client.stream("GET", "/api/v1/stream") as response:
            for chunk in response.iter_bytes():
                chunks.append(chunk)
        ended.set()

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(0.4)
    assert chunks, "the stream should be live before the session ends"
    assert not ended.is_set()
    world.auth.sessions.end(token)
    assert ended.wait(3), "the stream did not close"


def test_busy_stream_closes_after_session_ended(world: ApiWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_module, "KEEP_ALIVE_S", 0.05)
    token = world.session_token()
    client = TestClient(
        make_app(world),
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies={"netview_session": token},
    )
    ended = threading.Event()
    chunks: list[bytes] = []
    stop = threading.Event()

    def reader() -> None:
        with client.stream("GET", "/api/v1/stream") as response:
            for chunk in response.iter_bytes():
                chunks.append(chunk)
        ended.set()

    def busy() -> None:  # a state change faster than the keep-alive: the queue is never idle
        while not stop.is_set():
            world.notifier.state_changed()
            time.sleep(0.02)

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=busy, daemon=True).start()
    try:
        time.sleep(0.4)
        assert chunks, "the stream should be live before the session ends"
        assert not ended.is_set()
        world.auth.sessions.end(token)
        assert ended.wait(3), "a busy stream did not close after its session ended"
    finally:
        stop.set()


def test_stream_closes_when_the_user_loses_view(world: ApiWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_module, "KEEP_ALIVE_S", 0.05)
    world.add_user("kdoe")  # Default role: core.view
    token = world.session_token("kdoe")
    client = TestClient(
        make_app(world),
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies={"netview_session": token},
    )
    ended = threading.Event()
    chunks: list[bytes] = []

    def reader() -> None:
        with client.stream("GET", "/api/v1/stream") as response:
            for chunk in response.iter_bytes():
                chunks.append(chunk)
        ended.set()

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(0.4)
    assert chunks and not ended.is_set()
    world.auth.roles.update(SYSTEM_PRINCIPAL, "default", permissions=set())  # the session lives on
    assert world.auth.sessions.resolve(token) is not None
    assert ended.wait(3), "the stream stayed open after the user lost core.view"


def test_me_and_setup_report_the_password_minimum(world: ApiWorld, client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").json()["password_min_length"] == 12
    world.auth.policy.update(password_min_length=14)
    assert client.get("/api/v1/auth/me").json()["password_min_length"] == 14
    empty = build_world(seed_admin=False)
    anon = make_client(make_app(empty), user=None)
    assert anon.get("/api/v1/setup").json()["password_min_length"] == 12
