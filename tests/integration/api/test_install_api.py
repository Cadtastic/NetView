from api_helpers import ApiWorld, make_app, make_client
from fastapi.testclient import TestClient

from netview.application.ports.plugin_admin import PluginInfo
from netview.domain.errors import InstallError


def test_install_returns_202_and_job(client: TestClient, world: ApiWorld) -> None:
    response = client.post("/api/v1/plugins/install", json={"id": "alpha"})
    assert response.status_code == 202
    body = response.json()
    assert body["plugin_id"] == "alpha"
    assert body["state"] in {"queued", "downloading", "installing", "done"}
    assert len(body["job"]) == 32
    assert world.installer.installed == ["alpha"]


def test_install_conflict_409(client: TestClient, world: ApiWorld) -> None:
    world.admin.plugins["alpha"] = PluginInfo("alpha", "Alpha", "1", "d", "pending")
    response = client.post("/api/v1/plugins/install", json={"id": "alpha"})
    assert response.status_code == 409


def test_install_unknown_404(client: TestClient) -> None:
    assert client.post("/api/v1/plugins/install", json={"id": "nope"}).status_code == 404


def test_job_status(client: TestClient, world: ApiWorld) -> None:
    job = client.post("/api/v1/plugins/install", json={"id": "alpha"}).json()["job"]
    done = client.get(f"/api/v1/plugins/install/{job}").json()
    assert done["state"] == "done"
    assert done["error"] is None

    world.installer.error = InstallError("the plugin folder has no __init__.py")
    failed_job = client.post("/api/v1/plugins/install", json={"id": "alpha"}).json()["job"]
    failed = client.get(f"/api/v1/plugins/install/{failed_job}").json()
    assert failed["state"] == "failed"
    assert failed["error"] == "the plugin folder has no __init__.py"

    assert client.get("/api/v1/plugins/install/missing").status_code == 404


def test_post_needs_the_header_check(world: ApiWorld) -> None:
    bare = make_client(make_app(world), with_header=False)
    assert bare.post("/api/v1/plugins/install", json={"id": "alpha"}).status_code == 403
    assert world.installer.installed == []
