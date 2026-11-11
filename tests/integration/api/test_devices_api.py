from api_helpers import SELF_IP, ApiWorld
from fastapi.testclient import TestClient

KINDLE = "Jessi's Kindle"


def test_set_nickname_roundtrip(client: TestClient, world: ApiWorld) -> None:
    key = world.add_device("192.168.1.20")
    put = client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": KINDLE})
    assert put.status_code == 200
    got = client.get(f"/api/v1/devices/{key}")
    assert got.json()["nickname"] == KINDLE
    assert got.json()["display_name"] == KINDLE


def test_html_nickname_stored_verbatim(client: TestClient, world: ApiWorld) -> None:
    key = world.add_device("192.168.1.20")
    client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": "Café <b>"})
    assert client.get(f"/api/v1/devices/{key}").json()["nickname"] == "Café <b>"


def test_clear_nickname(client: TestClient, world: ApiWorld) -> None:
    key = world.add_device("192.168.1.20")
    client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": "x"})
    client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": None})
    assert client.get(f"/api/v1/devices/{key}").json()["nickname"] is None


def test_nickname_too_long_422(client: TestClient, world: ApiWorld) -> None:
    key = world.add_device("192.168.1.20")
    response = client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": "x" * 61})
    assert response.status_code == 422
    assert "60" in response.json()["error"]


def test_unknown_device_404(client: TestClient) -> None:
    response = client.get("/api/v1/devices/aa:bb:cc:00:00:99")
    assert response.status_code == 404
    assert "error" in response.json()
    assert client.put("/api/v1/devices/nope/nickname", json={"nickname": "x"}).status_code == 404


def test_devices_list_and_state(client: TestClient, world: ApiWorld) -> None:
    world.add_device("192.168.1.20")
    assert [d["ip"] for d in client.get("/api/v1/devices").json()] == ["192.168.1.20"]
    state = client.get("/api/v1/state").json()
    assert state["host"]["ip"] == "192.168.1.95"
    assert state["devices"][0]["ip"] == "192.168.1.20"
    assert state["capabilities"] == []


def test_watch_lifecycle(client: TestClient) -> None:
    created = client.post("/api/v1/watches", json={"spec": "192.168.1.5:80,443=NAS"})
    assert created.status_code == 200
    assert created.json() == {"ip": "192.168.1.5", "ports": [80, 443], "label": "NAS"}
    assert client.get("/api/v1/watches").json()[0]["ip"] == "192.168.1.5"
    assert client.delete("/api/v1/watches/192.168.1.5").status_code == 200
    assert client.get("/api/v1/watches").json() == []
    assert client.delete("/api/v1/watches/192.168.1.5").status_code == 404


def test_invalid_watch_422(client: TestClient) -> None:
    assert client.post("/api/v1/watches", json={"spec": "not-an-ip"}).status_code == 422


def test_events_endpoint(client: TestClient, world: ApiWorld) -> None:
    key = world.add_device("192.168.1.20")
    client.put(f"/api/v1/devices/{key}/nickname", json={"nickname": "Desk"})
    events = client.get("/api/v1/events", params={"limit": 5}).json()
    assert [e["kind"] for e in events] == ["nickname"]
    assert events[0]["key"] == key


def test_forget_self_is_422_and_the_row_stays(client: TestClient, world: ApiWorld) -> None:
    world.add_device(SELF_IP, None)
    response = client.delete("/api/v1/devices/self")
    assert response.status_code == 422
    assert "cannot be forgotten" in response.json()["error"]
    with world.uow() as uow:
        assert uow.devices.get("self") is not None
