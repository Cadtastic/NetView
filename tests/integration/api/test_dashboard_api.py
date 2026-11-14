import pytest
from api_helpers import ApiWorld, build_world, make_app, make_client

KEY = "core.tile.devices"
LAYOUT = {"version": 1, "order": [KEY], "hidden": [], "spans": {KEY: "half"}, "group": "none"}
OTHER = {"version": 1, "order": [], "hidden": [KEY], "spans": {}, "group": "plugin"}


@pytest.fixture
def world() -> ApiWorld:
    return build_world()


def client(world: ApiWorld, user: str | None = "admin"):
    return make_client(make_app(world), user=user)


def viewer(world: ApiWorld, name: str = "viewer"):
    world.grant(name, "core.view")
    return client(world, name)


def customizer(world: ApiWorld, name: str = "custom"):
    world.grant(name, "core.view", "core.dashboard")
    return client(world, name)


def test_viewer_gets_builtin_and_cannot_put(world):
    c = viewer(world)
    body = c.get("/api/v1/dashboard/layout").json()
    assert body == {"layout": None, "source": "builtin", "updated_ms": None, "default": None}
    assert c.put("/api/v1/dashboard/layout", json=LAYOUT).status_code == 403


def test_customizer_round_trip_and_reset(world):
    c = customizer(world)
    put = c.put("/api/v1/dashboard/layout", json=LAYOUT)
    assert put.status_code == 200
    assert put.json()["layout"] == LAYOUT
    got = c.get("/api/v1/dashboard/layout").json()
    assert got["source"] == "user"
    assert got["layout"] == LAYOUT
    assert isinstance(got["updated_ms"], int)
    after = c.delete("/api/v1/dashboard/layout").json()
    assert after["source"] == "builtin"
    assert c.get("/api/v1/dashboard/layout").json()["source"] == "builtin"


def test_bad_layout_is_422_with_field(world):
    c = customizer(world)
    bad = {**LAYOUT, "order": ["bad key"]}
    r = c.put("/api/v1/dashboard/layout", json=bad)
    assert r.status_code == 422
    assert "order" in str(r.json())


def test_admin_default_flow(world):
    v = viewer(world)
    c = customizer(world)
    c.put("/api/v1/dashboard/layout", json=LAYOUT)
    admin = client(world)
    put = admin.put("/api/v1/admin/dashboard/default", json={"layout": OTHER})
    assert put.status_code == 200
    assert put.json()["layout"] == OTHER
    got = v.get("/api/v1/dashboard/layout").json()
    assert got["source"] == "default"
    assert got["layout"] == OTHER
    info = admin.get("/api/v1/admin/dashboard/default").json()
    assert info["users_with_own_layout"] == 1
    assert info["layout"] == OTHER
    assert "Administrator" in info["roles_with_permission"]
    assert admin.delete("/api/v1/admin/dashboard/layouts").json() == {"removed": 1}
    assert c.get("/api/v1/dashboard/layout").json()["source"] == "default"


def test_admin_routes_need_core_system(world):
    c = customizer(world)
    assert c.get("/api/v1/admin/dashboard/default").status_code == 403
    assert c.put("/api/v1/admin/dashboard/default", json={"layout": OTHER}).status_code == 403
    assert c.delete("/api/v1/admin/dashboard/layouts").status_code == 403


def _big() -> bytes:
    return b'{"version": 1, "pad": "' + b"x" * 70_000 + b'"}'


def test_oversize_layout_body_is_413_before_parsing(world):
    c = customizer(world)
    res = c.put("/api/v1/dashboard/layout", content=_big(), headers={"Content-Type": "application/json"})
    assert res.status_code == 413
    assert "64 KB" in res.json()["error"]
    # nothing was saved
    assert c.get("/api/v1/dashboard/layout").json()["source"] == "builtin"


def test_oversize_body_without_content_length_is_413(world):
    c = customizer(world)

    def chunks():
        for _ in range(8):
            yield b"x" * 10_000

    res = c.put("/api/v1/dashboard/layout", content=chunks(), headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_oversize_default_body_is_413(world):
    c = client(world)
    headers = {"Content-Type": "application/json"}
    res = c.put("/api/v1/admin/dashboard/default", content=_big(), headers=headers)
    assert res.status_code == 413
    assert "64 KB" in res.json()["error"]


def test_a_body_at_the_limit_still_reaches_validation(world):
    c = customizer(world)
    body = b'{"version": 2, "pad": "' + b"x" * (65_536 - 40) + b'"}'
    assert len(body) <= 65_536
    res = c.put("/api/v1/dashboard/layout", content=body, headers={"Content-Type": "application/json"})
    assert res.status_code == 422
