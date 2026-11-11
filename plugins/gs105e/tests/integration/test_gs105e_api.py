from __future__ import annotations

import dataclasses
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from netview_local_plugins.gs105e.tools.fake_switch import FakeSwitch

from netview.infrastructure.settings import AppSettings
from netview.sdk.testing.fakes import FakeNetworkTools, FakeSnmpClient

PLUGINS = Path(__file__).resolve().parents[3]
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "fw-1.6.0.11"
BASE = "/api/v1/plugins/gs105e"
CONFIGURED = {"password": "secret", "host": "192.168.1.3"}


class StubSnmp(FakeSnmpClient):
    """An empty fake with the ``close`` the app calls on shutdown."""

    def close(self) -> None:
        return None


class Harness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.clients: list[TestClient] = []
        self.bodies: list[str] = []
        self.fake = FakeSwitch(FIX)
        self.passwords: set[str] = {"secret"}

    def make(self, settings: dict[str, Any], headers: dict[str, str] | None = None) -> TestClient:
        from netview_local_plugins.gs105e import plugin as plugin_module

        from netview.bootstrap import create_application

        password = settings.get("password")
        if isinstance(password, str):
            self.passwords.add(password)
        self.monkeypatch.setattr("netview_local_plugins.gs105e.client.http_fetch", self.fake)
        # no real scans or SNMP: the core scan job runs at startup
        self.monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: FakeNetworkTools())
        self.monkeypatch.setattr("netview.bootstrap.PysnmpClient", lambda: StubSnmp([]))
        # scheduled polls must not race the tests' own POST /poll: push their first run out of reach
        real_poll_job = plugin_module._poll_job

        def far_poll_job(*args: Any, **kwargs: Any) -> Any:
            return dataclasses.replace(real_poll_job(*args, **kwargs), initial_delay_s=3600)

        self.monkeypatch.setattr(plugin_module, "_poll_job", far_poll_job)
        app = create_application(
            AppSettings(
                data_dir=self.tmp_path / f"d{len(self.clients)}",
                subnet="192.168.1.0/24",
                plugins={"gs105e": settings},
                plugin_dirs=[PLUGINS],
            )
        )
        client = TestClient(
            app,
            base_url="http://localhost",
            headers={"X-Netview": "1"} if headers is None else headers,
        )
        client.__enter__()
        self.clients.append(client)
        return client

    def get(self, client: TestClient, path: str) -> Any:
        response = client.get(f"{BASE}{path}")
        self.bodies.append(response.text)
        return response

    def send(self, client: TestClient, method: str, path: str) -> Any:
        response = client.request(method, f"{BASE}{path}")
        self.bodies.append(response.text)
        return response

    def poll_and_wait(self, client: TestClient) -> None:
        assert self.send(client, "POST", "/poll").status_code == 202
        self.wait_idle(client)

    def wait_idle(self, client: TestClient) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not self.get(client, "/summary").json()["polling"]:
                return
            time.sleep(0.05)
        raise AssertionError("poll did not finish")


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    h = Harness(tmp_path, monkeypatch)
    try:
        yield h
    finally:
        try:
            for c in h.clients:
                c.__exit__(None, None, None)
        finally:
            for body in h.bodies:
                for password in h.passwords:
                    assert password not in body


def test_summary_before_any_poll(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    body = harness.get(client, "/summary").json()
    assert body["configured"] is True


def test_poll_then_ports(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    harness.poll_and_wait(client)
    ports = harness.get(client, "/ports").json()
    assert len(ports) == 5
    assert harness.get(client, "/ports/1").json()["link_mbps"] == 1000
    assert harness.get(client, "/ports/1/samples").status_code == 200
    assert harness.get(client, "/ports/1/samples?resolution=bogus").status_code == 422
    assert harness.get(client, "/ports/9/samples").status_code == 404


def test_unknown_port_404(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    response = harness.get(client, "/ports/9")
    assert response.status_code == 404
    assert response.json() == {"detail": "unknown port 9"}
    assert harness.get(client, "/ports/0").status_code == 404


def test_port_without_data_is_503(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    response = harness.get(client, "/ports/3")
    assert response.status_code == 503
    assert response.json() == {"detail": "no data for port 3 yet"}
    assert harness.get(client, "/ports/6").json() == {"detail": "unknown port 6"}


def test_config(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    harness.poll_and_wait(client)
    body = harness.get(client, "/config").json()
    assert body["vlans"]["mode"] == "off"
    assert body["qos"]["mode"] == "dot1p"


def test_pause_blocks_poll_and_resume_allows(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    paused = harness.send(client, "POST", "/pause")
    assert isinstance(paused.json()["paused_until_ms"], int)
    blocked = harness.send(client, "POST", "/poll")
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "polling is paused"}
    assert harness.send(client, "DELETE", "/pause").json() == {"paused_until_ms": None}
    assert harness.send(client, "POST", "/poll").status_code == 202
    harness.wait_idle(client)


def test_test_connection(harness: Harness) -> None:
    client = harness.make(CONFIGURED)
    body = harness.send(client, "POST", "/test").json()
    assert body["ok"] == "true"
    assert body["product"] == "GS105Ev2"


def test_poll_needs_header(harness: Harness) -> None:
    client = harness.make(CONFIGURED, headers={})
    response = client.post(f"{BASE}/poll")
    assert response.status_code == 403
    harness.bodies.append(response.text)


def test_wrong_password_blocks_poll(harness: Harness) -> None:
    client = harness.make({"password": "wrong", "host": "192.168.1.3"})
    assert harness.send(client, "POST", "/test").json()["ok"] == "false"
    blocked = harness.send(client, "POST", "/poll")
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "login failed; press Test connection"}


def test_not_configured_reaches_nothing(harness: Harness) -> None:
    client = harness.make({})
    assert harness.get(client, "/summary").json()["configured"] is False
    blocked = harness.send(client, "POST", "/poll")
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "not configured"}
    assert harness.fake.requests == []
