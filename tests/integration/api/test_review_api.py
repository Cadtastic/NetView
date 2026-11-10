from api_helpers import ApiWorld
from fastapi.testclient import TestClient

from netview.domain.errors import NoNetworkError, ScanInProgressError


def test_delete_device_204_and_gone(client: TestClient, world: ApiWorld) -> None:
    key = world.add_device("192.168.1.20")
    client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": "Desk"})
    assert client.delete(f"/api/v1/devices/{key}").status_code == 204
    assert client.get(f"/api/v1/devices/{key}").status_code == 404
    assert client.get("/api/v1/events").json()[0]["kind"] == "forgotten"
    with world.uow() as uow:
        assert uow.nicknames.get(key) == "Desk"


def test_delete_unknown_device_404(client: TestClient) -> None:
    response = client.delete("/api/v1/devices/aa:bb:cc:00:00:99")
    assert response.status_code == 404
    assert "error" in response.json()


def test_delete_needs_the_netview_header(world: ApiWorld) -> None:
    from api_helpers import make_app, make_client

    key = world.add_device("192.168.1.20")
    bare = make_client(make_app(world), with_header=False)
    assert bare.delete(f"/api/v1/devices/{key}").status_code == 403


def test_scan_no_network_503(client: TestClient, world: ApiWorld) -> None:
    def boom() -> None:
        raise NoNetworkError()

    world.services.run_scan = boom  # type: ignore[assignment]
    response = client.post("/api/v1/scan")
    assert response.status_code == 503
    assert response.json() == {"error": "no network: this device has no LAN address"}


def test_scan_in_progress_409(client: TestClient, world: ApiWorld) -> None:
    def busy() -> None:
        raise ScanInProgressError()

    world.services.run_scan = busy  # type: ignore[assignment]
    response = client.post("/api/v1/scan")
    assert response.status_code == 409
    assert response.json() == {"error": "scan already running"}
