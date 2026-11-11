from api_helpers import ApiWorld
from fastapi.testclient import TestClient

from netview.domain.inspection import InspectionReport
from netview.domain.watch import WatchProbe


def test_state_carries_the_parity_fields(client: TestClient) -> None:
    state = client.get("/api/v1/state").json()
    assert state["watch_status"] == []
    assert state["traffic"] == []
    assert state["traffic_totals"] == []
    assert state["inspected"] == {}


def test_a_new_watch_is_pending(client: TestClient) -> None:
    client.post("/api/v1/watches", json={"spec": "192.168.1.9:22,443=Switch"})

    [status] = client.get("/api/v1/state").json()["watch_status"]

    assert status["ip"] == "192.168.1.9"
    assert status["state"] == "pending"
    assert status["ports"] == [22, 443]
    assert status["label"] == "Switch"
    assert status["port_state"] == {}
    assert status["history"] == []


def test_watch_port_state_is_keyed_by_the_port_as_a_string(world: ApiWorld, client: TestClient) -> None:
    client.post("/api/v1/watches", json={"spec": "192.168.1.9:22,443"})
    monitor = world.services.state._monitor
    assert monitor is not None
    monitor.record(
        [WatchProbe("192.168.1.9", world.clock.now_ms(), True, True, None, 1.5, {22: "open", 443: "closed"})]
    )

    [status] = client.get("/api/v1/state").json()["watch_status"]

    assert status["port_state"] == {"22": "open", "443": "closed"}
    assert status["state"] == "degraded"


def test_watches_list_includes_status_fields(client: TestClient) -> None:
    client.post("/api/v1/watches", json={"spec": "192.168.1.9:22=Switch"})

    [item] = client.get("/api/v1/watches").json()

    assert item["ip"] == "192.168.1.9"
    assert item["ports"] == [22]
    assert item["label"] == "Switch"
    assert item["state"] == "pending"
    assert item["history"] == []
    assert item["port_state"] == {}


def test_inspected_maps_ip_to_the_newest_report_time(world: ApiWorld, client: TestClient) -> None:
    with world.uow() as u:
        u.inspections.save(InspectionReport("192.168.1.5", "top", 1000, 2500, []))
        u.commit()

    assert client.get("/api/v1/state").json()["inspected"] == {"192.168.1.5": 2500}


def test_devices_report_where_their_type_came_from(world: ApiWorld, client: TestClient) -> None:
    world.add_device("192.168.1.5")

    [device] = client.get("/api/v1/devices").json()

    assert device["type_source"] == ""
