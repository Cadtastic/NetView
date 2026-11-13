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
from netview.sdk.testing.addresses import api_base, static_base
from netview.sdk.testing.auth import admin_cookies
from netview.sdk.testing.fakes import FakeNetworkTools, FakeSnmpClient

WALK = Path(__file__).resolve().parents[1] / "fixtures" / "walk_basic.txt"
PLUGINS = Path(__file__).resolve().parents[3]
GUID = "3ae5ddcb-5e96-4dcc-b439-7b582a37b0f4"
BASE = ""
"""``/api/v1/plugins/<source_id>``; set by ``make_client`` once the app has numbered the plugin."""
STATIC = ""


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
def make_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snmp: GatedSnmp, plugin_seeds: Callable[..., Any]
) -> Iterator[Make]:
    clients: list[Any] = []
    monkeypatch.setattr("netview.bootstrap.PysnmpClient", lambda: snmp)
    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: FakeNetworkTools())

    def make(
        plugin_settings: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> TestClient:
        from netview.bootstrap import create_application

        seeds = plugin_seeds({GUID: plugin_settings} if plugin_settings is not None else {})
        app = create_application(
            AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24", plugins=seeds, plugin_dirs=[PLUGINS])
        )
        cm = TestClient(
            app,
            base_url="http://localhost",
            headers={"X-Netview": "1"} if headers is None else headers,
            cookies=admin_cookies(app.state.services),
        )
        cm.__enter__()
        clients.append(cm)
        global BASE, STATIC
        BASE, STATIC = api_base(app.state.services, GUID), static_base(app.state.services, GUID)
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
    listed = {p["guid"]: p for p in client.get("/api/v1/plugins").json()}
    assert listed[GUID]["state"] == "active"
    assert listed[GUID]["name"] == "NETGEAR GSM7248"
    assert listed[GUID]["id"] == BASE.rsplit("/", 1)[1] == str(listed[GUID]["source_id"])


def test_ui_module_and_static_files_are_served(make_client: Make) -> None:
    client = make_client()
    listed = {p["guid"]: p for p in client.get("/api/v1/plugins").json()}
    assert listed[GUID]["ui_module"] == f"{STATIC}/ui.js"
    for name in ("ui.js", "page.js", "port-grid.js", "gsm7248.css", "faceplate.svg"):
        response = client.get(f"{STATIC}/{name}")
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
    info = client.get(BASE).json()
    assert info["settings"]["community"] == "********"
    assert "s3cr3t" not in str(info)
    patched = client.patch(BASE, json={"settings": {"retries": 2, "community": "********"}})
    assert patched.status_code == 200
    assert patched.json()["settings"]["community"] == "********"
    assert "s3cr3t" not in patched.text
    # the stored community survived the round trip, so the switch is still reachable
    assert client.post(f"{BASE}/test", json={}).json()["ok"] == "true"


# ---- serial console ---------------------------------------------------------------------------


class FakeConsoleRunner:
    def __init__(self) -> None:
        self.result: tuple[int, bytes, str] = (0, b"NETVIEW:REPLY\n\r\nUser:", "")
        self.ran: list[list[str]] = []
        self.spawned: list[list[str]] = []

    def run(self, argv: list[str], timeout_s: float) -> tuple[int, bytes, str]:
        self.ran.append(argv)
        return self.result

    def spawn(self, argv: list[str]) -> None:
        self.spawned.append(argv)


@pytest.fixture
def console_runner(monkeypatch: pytest.MonkeyPatch) -> FakeConsoleRunner:
    from netview_local_plugins.gsm7248.console import SerialConsole

    runner = FakeConsoleRunner()
    monkeypatch.setattr(
        "netview_local_plugins.gsm7248.plugin.SerialConsole",
        lambda _real: SerialConsole(runner, platform="win32", which=lambda name: name),
    )
    return runner


def test_console_is_off_by_default_and_runs_nothing(
    make_client: Make, console_runner: FakeConsoleRunner
) -> None:
    client = make_client()
    state = client.get(f"{BASE}/console").json()
    assert state == {
        "enabled": False,
        "can_open": False,
        "probing": False,
        "host": None,
        "device": None,
        "status": None,
    }
    assert client.post(f"{BASE}/console/probe").status_code == 400
    assert client.post(f"{BASE}/console/open").status_code == 400
    assert console_runner.ran == []
    assert console_runner.spawned == []


def test_console_probe_reports_and_remembers_the_result(
    make_client: Make, console_runner: FakeConsoleRunner
) -> None:
    client = make_client({"console_enabled": True})
    before = client.get(f"{BASE}/console").json()
    assert (before["enabled"], before["can_open"], before["status"]) == (True, True, None)
    assert (before["host"], before["device"]) == ("192.168.1.36", "/dev/ttyS0")
    probed = client.post(f"{BASE}/console/probe").json()
    assert probed["status"]["state"] == "connected"
    assert probed["status"]["text"] == "User:"
    assert client.get(f"{BASE}/console").json()["status"]["state"] == "connected"
    assert len(console_runner.ran) == 1
    assert console_runner.ran[0][-2] == "root@192.168.1.36"


def test_console_open_ignores_anything_the_request_sends(
    make_client: Make, console_runner: FakeConsoleRunner
) -> None:
    client = make_client({"console_enabled": True})
    response = client.post(f"{BASE}/console/open", json={"command": "calc.exe", "host": "evil"})
    assert response.status_code == 202
    assert console_runner.spawned == [
        [
            "wt",
            "-w",
            "0",
            "new-tab",
            "--title",
            "GSM7248 console",
            "ssh",
            "-t",
            "root@192.168.1.36",
            "screen -D -R -S netview-gsm7248 /dev/ttyS0 38400",
        ]
    ]


def test_console_routes_need_the_netview_header(make_client: Make, console_runner: FakeConsoleRunner) -> None:
    client = make_client({"console_enabled": True}, headers={})
    assert client.post(f"{BASE}/console/open").status_code in (400, 403)
    assert client.post(f"{BASE}/console/probe").status_code in (400, 403)
    assert console_runner.spawned == []
    assert console_runner.ran == []
