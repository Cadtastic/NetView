from pathlib import Path

from api_helpers import ApiWorld, make_app, make_client
from fastapi import APIRouter
from fastapi.testclient import TestClient

from netview.application.plugins.ui import UiContribution


def test_list_and_get_plugin(client: TestClient) -> None:
    listed = client.get("/api/v1/plugins").json()
    assert [p["id"] for p in listed] == ["demo"]
    assert client.get("/api/v1/plugins/demo").json()["name"] == "Demo"
    assert client.get("/api/v1/plugins/nope").status_code == 404


def test_plugins_patch_settings_and_enable(client: TestClient, world: ApiWorld) -> None:
    response = client.patch("/api/v1/plugins/demo", json={"enabled": False, "settings": {"interval": 9}})
    assert response.status_code == 200
    body = response.json()
    assert body["settings"] == {"interval": 9}
    assert body["enabled"] is False
    assert body["restart_required"] is True
    assert world.admin.calls == [("settings", {"interval": 9}), ("enabled", False)]


def test_plugins_patch_invalid_settings_changes_nothing(client: TestClient, world: ApiWorld) -> None:
    response = client.patch("/api/v1/plugins/demo", json={"enabled": False, "settings": {"interval": -1}})
    assert response.status_code == 422
    assert world.admin.calls == []


def test_plugin_router_mounted(world: ApiWorld) -> None:
    router = APIRouter()

    @router.get("/hello")
    def hello() -> dict[str, str]:
        return {"hi": "there"}

    client = make_client(make_app(world, routers=[("demo", router)]))
    assert client.get("/api/v1/plugins/demo/hello").json() == {"hi": "there"}


def test_plugin_static_mounted(world: ApiWorld, tmp_path: Path) -> None:
    (tmp_path / "ui.js").write_text("export default 1;")
    client = make_client(make_app(world, ui=[("demo", UiContribution(tmp_path))]))
    response = client.get("/plugins/demo/static/ui.js")
    assert response.status_code == 200
    assert "export default" in response.text
