"""The real app: plugins are listed with their identity, and their routes live at the source_id."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import netview.bootstrap
from netview.bootstrap import create_application
from netview.infrastructure.settings import AppSettings
from netview.sdk.testing.auth import admin_cookies
from netview.sdk.testing.fakes import FakeNetworkTools

HEALTH_GUID = "9f4cd689-1a67-4c89-abff-ac9252568d97"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        netview.bootstrap, "SystemNetworkTools", lambda: FakeNetworkTools(gateway=None, fail=True)
    )
    app = create_application(AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24"))
    with TestClient(
        app,
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies=admin_cookies(app.state.services),
    ) as c:
        yield c


def test_list_carries_the_identity_fields(client: TestClient) -> None:
    listed = {p["guid"]: p for p in client.get("/api/v1/plugins").json()}
    health = listed[HEALTH_GUID]
    assert health["id"] == str(health["source_id"])
    assert health["display_name"] == "Health"
    assert health["plugin_type"] == "software"
    assert health["card_key"].startswith("entry_point:")
    assert health["uninstallable"] is False
    assert health["owns_data"] is True
    assert health["folder"] is None
    assert len({p["source_id"] for p in listed.values()}) == len(listed)  # every built-in is numbered


def test_a_route_is_reached_at_the_source_id_and_the_old_name_is_gone(client: TestClient) -> None:
    health = next(p for p in client.get("/api/v1/plugins").json() if p["guid"] == HEALTH_GUID)
    assert client.get(f"/api/v1/plugins/{health['source_id']}/summary").status_code == 200
    assert client.get("/api/v1/plugins/health/summary").status_code == 404
    assert client.get(f"/plugins/{health['source_id']}/static/ui.js").status_code == 200
    assert client.get("/plugins/health/static/ui.js").status_code == 404
