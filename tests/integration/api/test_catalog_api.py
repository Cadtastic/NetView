from api_helpers import ApiWorld, catalog_guid
from fastapi.testclient import TestClient

from netview.domain.errors import CatalogUnavailableError


def test_get_catalog_lists_available(client: TestClient) -> None:
    body = client.get("/api/v1/plugins/catalog").json()
    assert body["source"] == "bundled"
    assert body["stale"] is True
    assert body["error"] is None
    assert [p["guid"] for p in body["plugins"]] == [catalog_guid("alpha")]
    first = body["plugins"][0]
    assert first["installable"] is True
    assert first["reason"] is None
    assert first["path"] == "plugins/alpha"


def test_refresh_returns_error_text(world: ApiWorld, client: TestClient) -> None:
    ok = client.post("/api/v1/plugins/catalog/refresh").json()
    assert [p["guid"] for p in ok["plugins"]] == [catalog_guid("alpha"), catalog_guid("beta")]
    assert ok["stale"] is False
    world.fetcher.result = CatalogUnavailableError("Couldn't reach GitHub")
    bad = client.post("/api/v1/plugins/catalog/refresh").json()
    assert bad["error"] == "Couldn't reach GitHub"
    assert [p["guid"] for p in bad["plugins"]] == [catalog_guid("alpha"), catalog_guid("beta")]


def test_catalog_route_not_shadowed_by_plugin_id(client: TestClient) -> None:
    response = client.get("/api/v1/plugins/catalog")
    assert response.status_code == 200
    assert "plugins" in response.json()
