import pytest
from api_helpers import DEMO_GUID, DEMO_ID, ApiWorld, catalog_guid, make_app, make_client

from netview.application.auth.catalog import catalog_ids

KEY = "aa:bb:cc:dd:ee:01"
IP = "192.168.1.5"

# The doing-routes of the permission table (spec 6.1): (method, path, json body, permission).
DOING = [
    ("PUT", f"/api/v1/devices/{KEY}/nickname", {"nickname": "x"}, "core.rename"),
    ("DELETE", f"/api/v1/devices/{KEY}", None, "core.forget"),
    ("POST", "/api/v1/watches", {"spec": IP}, "core.watches"),
    ("DELETE", f"/api/v1/watches/{IP}", None, "core.watches"),
    ("POST", "/api/v1/scan", None, "core.scan"),
    ("POST", f"/api/v1/devices/{IP}/probe", None, "core.scan"),
    ("POST", "/api/v1/inspections", {"ip": IP, "ports": "common"}, "core.scan"),
    ("PATCH", "/api/v1/plugins/7", {"enabled": True}, "core.plugins"),
    ("PATCH", "/api/v1/plugins/7", {"settings": {"interval": 3}}, f"{DEMO_GUID}.configure"),
]

VIEWING = [
    "/api/v1/state",
    "/api/v1/devices",
    f"/api/v1/devices/{KEY}",
    "/api/v1/events",
    "/api/v1/metrics",
    f"/api/v1/inspections/{IP}",
    "/api/v1/watches",
    "/api/v1/plugins",
    "/api/v1/plugins/7",
    "/api/v1/plugins/catalog",
    "/api/v1/plugins/install/nope",
    "/api/v1/themes",
    "/api/v1/stream",
    "/docs",
    "/docs/init.js",
    "/openapi.json",
]


@pytest.fixture
def world(world: ApiWorld) -> ApiWorld:
    world.admin.plugins[DEMO_ID].settings_schema = {"type": "object"}  # gives demo a configure permission
    return world


def call(client, method: str, path: str, body):  # type: ignore[no-untyped-def]
    return client.request(method, path, json=body)


@pytest.mark.parametrize(("method", "path", "body", "permission"), DOING)
def test_core_route_needs_its_permission(
    world: ApiWorld, method: str, path: str, body: object, permission: str
) -> None:
    world.add_user("plain")  # the Default role: core.view only
    world.grant("holder", permission, "core.view")
    app = make_app(world)
    assert call(make_client(app, user="plain"), method, path, body).status_code == 403
    granted = call(make_client(app, user="holder"), method, path, body)
    assert granted.status_code != 403, granted.text
    assert call(make_client(app, user=None), method, path, body).status_code == 401
    assert call(make_client(app), method, path, body).status_code != 403  # administrators hold everything


@pytest.mark.parametrize("path", VIEWING)
def test_core_view_needed_for_every_read(world: ApiWorld, path: str) -> None:
    world.add_user("nobody", [])
    world.add_user("plain")
    app = make_app(world)
    assert make_client(app, user="nobody").get(path).status_code == 403
    if path != "/api/v1/stream":  # an open stream never finishes; its guard is the 403 above
        assert make_client(app, user="plain").get(path).status_code != 403


def test_patch_plugin_needs_core_view_even_with_empty_body(world: ApiWorld) -> None:
    world.add_user("nobody", [])
    nobody = make_client(make_app(world), user="nobody")
    assert nobody.patch("/api/v1/plugins/7", json={}).status_code == 403
    assert nobody.patch("/api/v1/plugins/missing", json={}).status_code == 403


def test_default_user_sees_dashboard_but_not_plugin_settings(world: ApiWorld) -> None:
    world.add_user("plain")
    plain = make_client(make_app(world), user="plain")
    assert plain.get("/api/v1/state").status_code == 200
    demo = plain.get("/api/v1/plugins").json()[0]
    assert demo["id"] == DEMO_ID
    assert demo["settings"] is None
    assert demo["settings_schema"] is None
    one = plain.get("/api/v1/plugins/7").json()
    assert one["settings"] is None
    assert one["name"] == "Demo"

    world.grant("configurer", "core.view", f"{DEMO_GUID}.configure")
    seen = make_client(make_app(world), user="configurer").get("/api/v1/plugins/7").json()
    assert seen["settings"] == {"interval": 5}
    assert seen["settings_schema"] == {"type": "object"}
    assert make_client(make_app(world)).get("/api/v1/plugins/7").json()["settings"] == {"interval": 5}


def test_install_admin_only_even_with_all_grantable_permissions(world: ApiWorld) -> None:
    everything = sorted(catalog_ids(world.auth.catalog()))
    assert "core.install" not in everything
    world.grant("almost", *everything)
    almost = make_client(make_app(world), user="almost")
    assert almost.post("/api/v1/plugins/install", json={"guid": catalog_guid("alpha")}).status_code == 403
    assert almost.post("/api/v1/plugins/catalog/refresh").status_code == 403
    admin = make_client(make_app(world))
    assert admin.post("/api/v1/plugins/catalog/refresh").status_code == 200
    assert admin.post("/api/v1/plugins/install", json={"guid": catalog_guid("alpha")}).status_code == 202


def test_patch_plugin_enabled_needs_core_plugins_settings_needs_configure(world: ApiWorld) -> None:
    world.grant("toggler", "core.plugins", "core.view")
    world.grant("configurer", "core.view", f"{DEMO_GUID}.configure")
    world.grant("both", "core.view", "core.plugins", f"{DEMO_GUID}.configure")
    app = make_app(world)
    toggler = make_client(app, user="toggler")
    configurer = make_client(app, user="configurer")
    both = make_client(app, user="both")

    assert toggler.patch("/api/v1/plugins/7", json={"enabled": False}).status_code == 200
    assert toggler.patch("/api/v1/plugins/7", json={"settings": {"interval": 7}}).status_code == 403
    assert configurer.patch("/api/v1/plugins/7", json={"enabled": True}).status_code == 403
    assert configurer.patch("/api/v1/plugins/7", json={"settings": {"interval": 7}}).status_code == 200
    assert world.admin.calls == [("enabled", False), ("settings", {"interval": 7})]

    world.admin.calls.clear()
    refused = toggler.patch("/api/v1/plugins/7", json={"enabled": True, "settings": {"interval": 9}})
    assert refused.status_code == 403
    assert world.admin.calls == []  # a refused request changes nothing
    ok = both.patch("/api/v1/plugins/7", json={"enabled": True, "settings": {"interval": 9}})
    assert ok.status_code == 200
    assert world.admin.calls == [("settings", {"interval": 9}), ("enabled", True)]
