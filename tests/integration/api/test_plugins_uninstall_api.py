"""POST /api/v1/plugins/uninstall, and the web addresses of a plugin once it is gone."""

import shutil
from pathlib import Path

import pytest
from api_helpers import DEMO_GUID, DEMO_ID, ApiWorld, make_client
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from netview.application.plugins.ui import UiContribution
from netview.application.ports.plugin_admin import UninstallResult
from netview.presentation.api.app import create_app


@pytest.fixture
def gone() -> set[str]:
    return set()


@pytest.fixture
def app(world: ApiWorld, tmp_path: Path, gone: set[str]) -> FastAPI:
    static = tmp_path / "static"
    static.mkdir()
    (static / "ui.js").write_text("export default 1")
    router = APIRouter()

    @router.get("/data")
    def data() -> dict[str, str]:
        return {"secret": "x"}

    @router.post("/poll")
    def poll() -> dict[str, bool]:
        return {"ok": True}

    info = world.admin.plugins[DEMO_ID]
    info.folder = "demo"
    info.capabilities = ["api", "web_ui"]

    def uninstall(folder: str, delete_data: bool) -> UninstallResult:
        world.admin.calls.append(("uninstall", (folder, delete_data)))
        gone.add(DEMO_ID)
        return UninstallResult(True, None)

    world.admin.uninstall = uninstall  # type: ignore[method-assign]
    world.add_user("plain")
    world.grant("viewer", f"{DEMO_GUID}.view")
    return create_app(
        world.services,
        [(DEMO_ID, router)],
        [(DEMO_ID, UiContribution(static))],
        {"localhost", "127.0.0.1", "[::1]"},
        guids=world.admin.guids(),
        present=lambda source_id: source_id not in gone,
    )


def test_uninstall_returns_result(app: FastAPI, world: ApiWorld) -> None:
    client = make_client(app)
    response = client.post("/api/v1/plugins/uninstall", json={"folder": "demo"})
    assert response.status_code == 200
    assert response.json() == {"finished": True, "error": None}
    assert world.admin.calls == [("uninstall", ("demo", False))]
    client.post("/api/v1/plugins/uninstall", json={"folder": "demo", "delete_data": True})
    assert world.admin.calls[-1] == ("uninstall", ("demo", True))


def test_uninstall_requires_admin(app: FastAPI, world: ApiWorld) -> None:
    for user, status in (("viewer", 403), ("plain", 403), (None, 401)):
        client = make_client(app, user=user)
        assert client.post("/api/v1/plugins/uninstall", json={"folder": "demo"}).status_code == status
    assert world.admin.calls == []


def test_uninstall_needs_the_header_check(app: FastAPI, world: ApiWorld) -> None:
    bare = make_client(app, with_header=False)
    assert bare.post("/api/v1/plugins/uninstall", json={"folder": "demo"}).status_code == 403
    assert world.admin.calls == []


@pytest.mark.parametrize("user", ["admin", "viewer", "plain"])
def test_routes_404_after_uninstall(app: FastAPI, gone: set[str], user: str) -> None:
    client: TestClient = make_client(app, user=user)
    expected = 403 if user == "plain" else 200
    assert client.get(f"/api/v1/plugins/{DEMO_ID}/data").status_code == expected
    assert client.get(f"/plugins/{DEMO_ID}/static/ui.js").status_code == expected

    gone.add(DEMO_ID)

    api = client.get(f"/api/v1/plugins/{DEMO_ID}/data")
    static = client.get(f"/plugins/{DEMO_ID}/static/ui.js")
    assert api.status_code == 404 and b"secret" not in api.content
    assert static.status_code == 404 and b"export" not in static.content
    assert client.post(f"/api/v1/plugins/{DEMO_ID}/poll").status_code == 404


def test_signed_out_still_asks_to_sign_in(app: FastAPI, gone: set[str]) -> None:
    gone.add(DEMO_ID)
    client = make_client(app, user=None)
    assert client.get(f"/api/v1/plugins/{DEMO_ID}/data").status_code == 401


def test_other_plugins_unaffected(app: FastAPI, gone: set[str]) -> None:
    gone.add("99")
    client = make_client(app, user="admin")
    assert client.get(f"/api/v1/plugins/{DEMO_ID}/data").status_code == 200
    assert client.get(f"/plugins/{DEMO_ID}/static/ui.js").status_code == 200


def test_static_404_when_the_folder_is_gone(app: FastAPI, gone: set[str], tmp_path: Path) -> None:
    gone.add(DEMO_ID)
    shutil.rmtree(tmp_path / "static")
    client = make_client(app, user="viewer")
    assert client.get(f"/plugins/{DEMO_ID}/static/ui.js").status_code == 404
