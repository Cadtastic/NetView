from pathlib import Path

from api_helpers import DEMO_ID, ApiWorld, make_app, make_client
from fastapi import APIRouter
from fastapi.testclient import TestClient

from netview.application.plugins.ui import UiContribution
from netview.application.ports.plugin_admin import PluginInfo


def test_list_and_get_plugin(client: TestClient) -> None:
    listed = client.get("/api/v1/plugins").json()
    assert [p["id"] for p in listed] == [DEMO_ID]
    assert client.get("/api/v1/plugins/7").json()["name"] == "Demo"
    assert client.get("/api/v1/plugins/nope").status_code == 404


def test_plugins_patch_settings_and_enable(client: TestClient, world: ApiWorld) -> None:
    response = client.patch("/api/v1/plugins/7", json={"enabled": False, "settings": {"interval": 9}})
    assert response.status_code == 200
    body = response.json()
    assert body["settings"] == {"interval": 9}
    assert body["enabled"] is False
    assert body["restart_required"] is True
    assert world.admin.calls == [("settings", {"interval": 9}), ("enabled", False)]


def test_plugins_patch_invalid_settings_changes_nothing(client: TestClient, world: ApiWorld) -> None:
    response = client.patch("/api/v1/plugins/7", json={"enabled": False, "settings": {"interval": -1}})
    assert response.status_code == 422
    assert world.admin.calls == []


def test_invalid_settings_422_names_each_field(client: TestClient) -> None:
    response = client.patch("/api/v1/plugins/7", json={"settings": {"interval": -1}})
    assert response.status_code == 422
    assert response.json() == {
        "error": "interval must be positive",
        "fields": {"interval": "Must be positive"},
    }


def test_plugin_reports_whether_it_is_configured(client: TestClient, world: ApiWorld) -> None:
    body = client.get("/api/v1/plugins/7").json()
    assert body["configured"] is True
    assert body["config_errors"] == {}
    world.admin.plugins[DEMO_ID].config_errors = {"interval": "Required"}
    body = client.get("/api/v1/plugins/7").json()
    assert body["configured"] is False
    assert body["config_errors"] == {"interval": "Required"}


def test_plugin_router_mounted(world: ApiWorld) -> None:
    router = APIRouter()

    @router.get("/hello")
    def hello() -> dict[str, str]:
        return {"hi": "there"}

    client = make_client(make_app(world, routers=[(DEMO_ID, router)]))
    assert client.get("/api/v1/plugins/7/hello").json() == {"hi": "there"}


def test_plugin_static_mounted(world: ApiWorld, tmp_path: Path) -> None:
    (tmp_path / "ui.js").write_text("export default 1;")
    client = make_client(make_app(world, ui=[(DEMO_ID, UiContribution(tmp_path))]))
    response = client.get("/plugins/7/static/ui.js")
    assert response.status_code == 200
    assert "export default" in response.text


def _add_pending(world: ApiWorld) -> None:
    world.admin.plugins["fresh"] = PluginInfo("fresh", "Fresh", "0.1.0", "New", "pending", source="folder")


def test_pending_plugin_listed_with_state(client: TestClient, world: ApiWorld) -> None:
    _add_pending(world)
    listed = {p["id"]: p for p in client.get("/api/v1/plugins").json()}
    assert listed["fresh"]["state"] == "pending"
    assert listed["fresh"]["source"] == "folder"
    assert listed[DEMO_ID]["source"] == "builtin"


def test_patch_pending_is_409(client: TestClient, world: ApiWorld) -> None:
    _add_pending(world)
    response = client.patch("/api/v1/plugins/fresh", json={"enabled": False})
    assert response.status_code == 409
    assert "loads the next time netview starts" in response.json()["error"]
    assert world.admin.calls == []
