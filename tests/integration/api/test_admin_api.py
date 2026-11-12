from api_helpers import PASSWORD, ApiWorld, make_app, make_client
from fastapi.testclient import TestClient


def admin_client(world: ApiWorld) -> TestClient:
    return make_client(make_app(world))


def test_admin_users_crud_and_builtin_protections_map_to_422(world: ApiWorld) -> None:
    client = admin_client(world)
    created = client.post(
        "/api/v1/admin/users",
        json={"username": " KDoe ", "display_name": "K Doe", "password": PASSWORD},
    )
    assert created.status_code == 201
    user = created.json()
    assert user["username"] == "kdoe"
    assert user["role_ids"] == ["default"]
    assert user["must_change_password"] is True
    assert "password" not in user

    listed = client.get("/api/v1/admin/users").json()
    assert [u["username"] for u in listed] == ["admin", "kdoe"]

    patched = client.patch(
        f"/api/v1/admin/users/{user['id']}", json={"display_name": "Kay", "enabled": False}
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Kay"
    assert patched.json()["enabled"] is False

    reset = client.post(
        f"/api/v1/admin/users/{user['id']}/password", json={"password": "another long password"}
    )
    assert reset.status_code == 204
    assert (
        client.post(f"/api/v1/admin/users/{user['id']}/password", json={"password": "short"}).status_code
        == 422
    )

    assert client.delete(f"/api/v1/admin/users/{user['id']}").status_code == 204
    assert client.delete(f"/api/v1/admin/users/{user['id']}").status_code == 404

    admin_id = listed[0]["id"]
    assert client.delete(f"/api/v1/admin/users/{admin_id}").status_code == 422
    assert client.patch(f"/api/v1/admin/users/{admin_id}", json={"enabled": False}).status_code == 422
    assert client.patch(f"/api/v1/admin/users/{admin_id}", json={"role_ids": ["default"]}).status_code == 422


def test_duplicate_username_is_409_and_bad_input_422(world: ApiWorld) -> None:
    client = admin_client(world)
    body = {"username": "kdoe", "password": PASSWORD}
    assert client.post("/api/v1/admin/users", json=body).status_code == 201
    assert client.post("/api/v1/admin/users", json=body).status_code == 409
    assert (
        client.post("/api/v1/admin/users", json={"username": "a b", "password": PASSWORD}).status_code == 422
    )
    unknown = client.post("/api/v1/admin/users", json={**body, "username": "x1", "role_ids": ["nope"]})
    assert unknown.status_code == 422


def test_admin_roles_and_permissions_catalog_shape(world: ApiWorld) -> None:
    client = admin_client(world)
    groups = client.get("/api/v1/admin/permissions").json()
    core = groups[0]
    assert core["owner"] == "core"
    assert core["off"] is False
    ids = [p["id"] for p in core["permissions"]]
    assert ids[0] == "core.view"
    assert "core.users" in ids
    install = next(p for p in core["permissions"] if p["id"] == "core.install")
    assert install["locked"] == "Administrator only: installing runs downloaded code"
    assert set(core["permissions"][0]) == {"id", "label", "description", "dangerous", "locked"}

    roles = client.get("/api/v1/admin/roles").json()
    assert [r["id"] for r in roles] == ["administrator", "default"]
    assert roles[1]["permissions"] == ["core.view"]
    assert roles[0]["user_count"] == 1

    created = client.post("/api/v1/admin/roles", json={"name": "Operators", "permissions": ["core.scan"]})
    assert created.status_code == 201
    assert created.json() == {
        "id": "operators",
        "name": "Operators",
        "builtin": False,
        "permissions": ["core.scan"],
        "user_count": 0,
    }
    assert client.post("/api/v1/admin/roles", json={"name": "Operators"}).status_code == 409
    bad = client.post("/api/v1/admin/roles", json={"name": "Bad", "permissions": ["core.install"]})
    assert bad.status_code == 422
    assert "bad" not in [r["id"] for r in client.get("/api/v1/admin/roles").json()]

    patched = client.patch(
        "/api/v1/admin/roles/operators", json={"name": "Ops", "permissions": ["core.scan", "core.rename"]}
    )
    assert patched.status_code == 200
    assert patched.json()["permissions"] == ["core.rename", "core.scan"]
    assert client.patch("/api/v1/admin/roles/default", json={"name": "Other"}).status_code == 422
    assert client.delete("/api/v1/admin/roles/default").status_code == 422
    assert client.delete("/api/v1/admin/roles/operators").status_code == 204
    assert client.delete("/api/v1/admin/roles/operators").status_code == 404


def test_general_get_patch_and_floor_422(world: ApiWorld) -> None:
    client = admin_client(world)
    assert client.get("/api/v1/admin/general").json() == {
        "password_min_length": 12,
        "session_idle_s": 28800,
        "session_max_s": 604800,
        "lockout_failures": 5,
        "lockout_window_s": 900,
        "lockout_s": 900,
        "mode": "home",
    }
    ok = client.patch("/api/v1/admin/general", json={"password_min_length": 10, "lockout_failures": 3})
    assert ok.status_code == 200
    assert ok.json()["password_min_length"] == 10
    assert client.get("/api/v1/admin/general").json()["lockout_failures"] == 3
    floor = client.patch("/api/v1/admin/general", json={"password_min_length": 7})
    assert floor.status_code == 422
    assert "password_min_length" in floor.json()["fields"]
    assert client.patch("/api/v1/admin/general", json={"mode": "enterprise"}).status_code == 422


def test_admin_routes_need_their_permissions(world: ApiWorld) -> None:
    world.grant("usermgr", "core.users")
    world.grant("sysmgr", "core.system")
    users = make_client(make_app(world), user="usermgr")
    system = make_client(make_app(world), user="sysmgr")
    assert users.get("/api/v1/admin/users").status_code == 200
    assert users.get("/api/v1/admin/roles").status_code == 200
    assert users.get("/api/v1/admin/permissions").status_code == 200
    assert users.get("/api/v1/admin/general").status_code == 403
    assert users.patch("/api/v1/admin/general", json={}).status_code == 403
    assert system.get("/api/v1/admin/general").status_code == 200
    assert system.get("/api/v1/admin/users").status_code == 403
    assert make_client(make_app(world), user=None).get("/api/v1/admin/users").status_code == 401


def test_user_manager_cannot_act_on_users_holding_permissions_they_lack(world: ApiWorld) -> None:
    world.grant("usermgr", "core.users", "core.view")
    world.grant("sysuser", "core.system")
    target = next(u for u in world.auth.users.list() if u.username == "sysuser")
    manager = make_client(make_app(world), user="usermgr")
    url = f"/api/v1/admin/users/{target.id}"
    assert manager.post(f"{url}/password", json={"password": PASSWORD + "-new"}).status_code == 403
    assert manager.patch(url, json={"enabled": False}).status_code == 403
    assert manager.delete(url).status_code == 403
    still = next(u for u in world.auth.users.list() if u.username == "sysuser")
    assert still.enabled
