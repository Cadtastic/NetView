from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from netview.infrastructure.settings import AppSettings
from netview.sdk import SnmpTimeout
from netview.sdk.testing.fakes import FakeNetworkTools, FakeSnmpClient

WALK = Path(__file__).resolve().parents[3] / "fixtures" / "gsm7248" / "walk_basic.txt"
BASE = "/api/v1/plugins/gsm7248"


class GatedSnmp(FakeSnmpClient):
    """A fake whose walks can be held back, and which has the ``close`` the app calls on shutdown."""

    def __init__(self, path: Path) -> None:
        super().__init__(FakeSnmpClient.from_walk_file(path).rows.items())
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def walk(self, target: Any, prefix: Any, max_rows: int = 10_000) -> Any:
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(10)
        return super().walk(target, prefix, max_rows)

    def close(self) -> None:
        return None


Make = Callable[..., TestClient]


@pytest.fixture
def snmp() -> GatedSnmp:
    return GatedSnmp(WALK)


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snmp: GatedSnmp) -> Iterator[Make]:
    clients: list[Any] = []
    monkeypatch.setattr("netview.bootstrap.PysnmpClient", lambda: snmp)
    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: FakeNetworkTools())

    def make(
        plugin_settings: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> TestClient:
        from netview.bootstrap import create_application

        seeds = {"gsm7248": plugin_settings} if plugin_settings is not None else {}
        app = create_application(AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24", plugins=seeds))
        cm = TestClient(
            app,
            base_url="http://localhost",
            headers={"X-Netview": "1"} if headers is None else headers,
        )
        cm.__enter__()
        clients.append(cm)
        return cm

    yield make
    for c in clients:
        c.__exit__(None, None, None)


CONFIGURED = {"snmp_version": "2c", "community": "s3cr3t"}


def poll_and_wait(client: TestClient) -> None:
    """POST /poll, then wait for the status, topology and bridge results (counters run last)."""
    assert client.post(f"{BASE}/poll").status_code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if client.get(f"{BASE}/macs").json() and client.get(f"{BASE}/vlans").json():
            return
        time.sleep(0.05)
    raise AssertionError("poll did not finish")


def test_plugin_loads_and_migrates(make_client: Make) -> None:
    client = make_client()
    listed = {p["id"]: p for p in client.get("/api/v1/plugins").json()}
    assert listed["gsm7248"]["state"] == "active"
    assert listed["gsm7248"]["name"] == "NETGEAR GSM7248"


def test_ui_module_and_static_files_are_served(make_client: Make) -> None:
    client = make_client()
    listed = {p["id"]: p for p in client.get("/api/v1/plugins").json()}
    assert listed["gsm7248"]["ui_module"] == "/plugins/gsm7248/static/ui.js"
    for name in ("ui.js", "page.js", "port-grid.js", "gsm7248.css"):
        response = client.get(f"/plugins/gsm7248/static/{name}")
        assert response.status_code == 200, name
        assert response.text.strip()


def test_summary_not_configured(make_client: Make) -> None:
    body = make_client().get(f"{BASE}/summary").json()
    assert body["configured"] is False
    assert body["reachable"] is None
    assert body["switch"] is None
    assert body["ports"] == {"total": 0, "up": 0, "uplinks": 0}


def test_ports_endpoint_shape(make_client: Make) -> None:
    client = make_client(CONFIGURED)
    poll_and_wait(client)
    ports = client.get(f"{BASE}/ports").json()
    assert len(ports) >= 48
    p5 = next(p for p in ports if p["name"] == "0/5")
    assert p5["oper_up"] is True
    assert p5["speed_mbps"] == 1000
    assert p5["pvid"] == 1
    assert {"untagged", "tagged"} == set(p5["vlans"])
    assert p5["devices"]
    summary = client.get(f"{BASE}/summary").json()
    assert summary["configured"] is True
    assert summary["reachable"] is True
    assert summary["ports"]["up"] >= 1


def test_port_by_encoded_name(make_client: Make) -> None:
    client = make_client(CONFIGURED)
    poll_and_wait(client)
    response = client.get(f"{BASE}/ports/0%2F5")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "0/5"
    assert "mac_history" in body
    samples = client.get(f"{BASE}/ports/0%2F5/samples?resolution=raw")
    assert samples.status_code == 200
    assert isinstance(samples.json(), list)
    assert client.get(f"{BASE}/ports/0%2F5/samples?resolution=bogus").status_code == 422


def test_unknown_port_404(make_client: Make) -> None:
    client = make_client(CONFIGURED)
    poll_and_wait(client)
    assert client.get(f"{BASE}/ports/9%2F9").status_code == 404
    assert client.get(f"{BASE}/ports/9%2F9/samples").status_code == 404


def test_macs_and_vlans(make_client: Make) -> None:
    client = make_client(CONFIGURED)
    poll_and_wait(client)
    macs = client.get(f"{BASE}/macs").json()
    assert any(m["mac"] == "b8:ca:3a:67:7d:ef" and m["port"] == "0/5" for m in macs)
    vlans = client.get(f"{BASE}/vlans").json()
    assert vlans[0]["vid"] == 1


def test_poll_conflict_409(make_client: Make, snmp: GatedSnmp) -> None:
    client = make_client(CONFIGURED)
    snmp.gate = threading.Event()
    try:
        assert client.post(f"{BASE}/poll").status_code == 202
        assert snmp.entered.wait(5)
        second = client.post(f"{BASE}/poll")
        assert second.status_code == 409
        assert second.json() == {"detail": "poll already running"}
    finally:
        snmp.gate.set()


def test_poll_requires_x_netview_header(make_client: Make) -> None:
    client = make_client(CONFIGURED, headers={})
    assert client.post(f"{BASE}/poll").status_code == 403
    assert client.post(f"{BASE}/test", json={}).status_code == 403


def test_test_route_never_returns_secret(make_client: Make, snmp: GatedSnmp) -> None:
    client = make_client(CONFIGURED)
    ok = client.post(f"{BASE}/test", json={})
    assert ok.status_code == 200
    assert ok.json()["ok"] == "true"
    assert "s3cr3t" not in ok.text
    snmp.fail_with = SnmpTimeout("no answer from s3cr3t")
    bad = client.post(f"{BASE}/test", json={})
    assert bad.json()["ok"] == "false"
    assert bad.json()["error"].startswith("SnmpTimeout")
    assert "s3cr3t" not in bad.text


def test_test_route_not_configured(make_client: Make) -> None:
    body = make_client().post(f"{BASE}/test", json={}).json()
    assert body["ok"] == "false"
    assert "not configured" in body["error"]


def test_settings_api_masks_community(make_client: Make) -> None:
    client = make_client(CONFIGURED)
    info = client.get("/api/v1/plugins/gsm7248").json()
    assert info["settings"]["community"] == "********"
    assert "s3cr3t" not in str(info)
    patched = client.patch(
        "/api/v1/plugins/gsm7248", json={"settings": {"retries": 2, "community": "********"}}
    )
    assert patched.status_code == 200
    assert patched.json()["settings"]["community"] == "********"
    assert "s3cr3t" not in patched.text
    # the stored community survived the round trip, so the switch is still reachable
    assert client.post(f"{BASE}/test", json={}).json()["ok"] == "true"
