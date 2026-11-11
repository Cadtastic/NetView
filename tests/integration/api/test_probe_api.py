from typing import Any

from api_helpers import ApiWorld
from fastapi.testclient import TestClient

from netview.application.capabilities import Capability
from netview.domain.inspection import ReportSection


class FakeInspection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def inspect(self, ip: str, ports_spec: str) -> list[ReportSection]:
        self.calls.append((ip, ports_spec))
        return [ReportSection("fake", "ports", "Open ports", {"text": ["22 ssh"]})]


def test_probe_runs_the_common_inspection_and_stores_nothing(world: ApiWorld, client: TestClient) -> None:
    provider = FakeInspection()
    world.registry.register("fake", Capability.INSPECTION, provider)

    response = client.post("/api/v1/devices/192.168.1.5/probe")

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["ip"] == "192.168.1.5"
    assert body["ports_spec"] == "common"
    assert body["sections"][0]["title"] == "Open ports"
    assert provider.calls == [("192.168.1.5", "common")]
    assert client.get("/api/v1/inspections/192.168.1.5").status_code == 404
    assert [e for e in client.get("/api/v1/events").json() if e["kind"] == "inspected"] == []


def test_probe_without_an_inspection_plugin_is_409(client: TestClient) -> None:
    response = client.post("/api/v1/devices/192.168.1.5/probe")
    assert response.status_code == 409
    assert response.json() == {"error": "no enabled plugin provides inspection"}


def test_probe_rejects_a_non_ipv4_address(client: TestClient) -> None:
    assert client.post("/api/v1/devices/abc/probe").status_code == 422
    assert client.post("/api/v1/devices/1.2.3.4;ls/probe").status_code == 422


def test_inspection_ports_must_be_a_port_spec(client: TestClient) -> None:
    for bad in ("1-1024; rm", "", "70000a", "1-", "-5", "1,,2", "top all"):
        response = client.post("/api/v1/inspections", json={"ip": "192.168.1.5", "ports": bad})
        assert response.status_code == 422, bad


def test_inspection_accepts_every_valid_port_spec(world: ApiWorld, client: TestClient) -> None:
    provider = FakeInspection()
    world.registry.register("fake", Capability.INSPECTION, provider)
    good = ("top", "all", "common", "22", "22,80", "1-1024", "22,80,8000-8100")
    for spec in good:
        response = client.post("/api/v1/inspections", json={"ip": "192.168.1.5", "ports": spec})
        assert response.status_code == 200, spec
    assert [c[1] for c in provider.calls] == list(good)
