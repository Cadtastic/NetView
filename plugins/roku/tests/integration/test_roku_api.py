"""The Roku plugin through NetView's real app: folder discovery, permissions, routes and jobs."""

from __future__ import annotations

import importlib.metadata
import json
import re
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from netview_local_plugins.roku import plugin as plugin_module
from netview_local_plugins.roku import plugin_class as RokuPlugin
from netview_local_plugins.roku import routes
from netview_local_plugins.roku.ecp import EcpResponse
from netview_local_plugins.roku.settings import RokuSettings

from netview.infrastructure.plugins.discovery import discover_plugin_classes
from netview.infrastructure.settings import AppSettings
from netview.presentation.api.security import CSP
from netview.sdk.testing.auth import admin_cookies
from netview.sdk.testing.fakes import FakeNetworkTools, FakeServiceProbes

ROKU_DIR = Path(__file__).resolve().parents[2]
PLUGINS_DIR = ROKU_DIR.parent
FIXTURES = ROKU_DIR / "tests" / "fixtures"
BASE = "/api/v1/plugins/roku"
TV_IP = "192.168.1.60"
ON = (FIXTURES / "device-info-on.xml").read_text()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8


class FakeTransport:
    def __init__(self) -> None:
        self.tvs: dict[str, str] = {}  # ip -> device-info XML
        self.posts: list[str] = []
        self.limited_commands = False
        self.icon: tuple[str, bytes] = ("image/png", PNG)
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def __call__(self, method: str, url: str, timeout_s: float) -> EcpResponse:
        match = re.match(r"http://([\d.]+):8060(/.*)$", url)
        assert match, url
        ip, path = match.groups()
        body = self.tvs.get(ip)
        if body is None:
            raise TimeoutError("timed out")
        if self.gate is not None and path == "/query/device-info":
            self.entered.set()
            self.gate.wait(10)
        if path == "/query/device-info":
            return EcpResponse(200, {}, body.encode())
        if method == "POST":
            if self.limited_commands:
                return EcpResponse(403, {}, b"")
            self.posts.append(path)
            return EcpResponse(200, {}, b"")
        if path.startswith("/query/icon/"):
            return EcpResponse(200, {"Content-Type": self.icon[0]}, self.icon[1])
        return EcpResponse(200, {}, b"<x/>")


Make = Callable[..., TestClient]


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: FakeTransport) -> Iterator[Make]:
    clients: list[TestClient] = []
    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: FakeNetworkTools())
    monkeypatch.setattr("netview.bootstrap.SystemServiceProbes", lambda **kw: FakeServiceProbes())
    monkeypatch.setattr(plugin_module, "urllib_transport", transport)

    def make(settings: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> TestClient:
        from netview.bootstrap import create_application

        seeds = {"roku": settings} if settings is not None else {}
        app = create_application(
            AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24", plugins=seeds, plugin_dirs=[PLUGINS_DIR])
        )
        client = TestClient(
            app,
            base_url="http://localhost",
            headers={"X-Netview": "1"} if headers is None else headers,
            cookies=admin_cookies(app.state.services),
        )
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def save_tv(client: TestClient, transport: FakeTransport) -> str:
    transport.tvs[TV_IP] = ON
    document = {"schema": "netview.roku/tvs@1", "tvs": [{"ip": TV_IP, "name": "Living Room TV"}]}
    response = client.put(f"{BASE}/tvs/document", json={"text": json.dumps(document)})
    assert response.status_code == 200, response.text
    tvs = client.get(f"{BASE}/tvs").json()["tvs"]
    assert len(tvs) == 1
    return str(tvs[0]["id"])


def test_folder_discovery_finds_roku_without_error() -> None:
    found = [d for d in discover_plugin_classes(extra_dirs=[PLUGINS_DIR]) if d.source.endswith("roku")]
    assert len(found) == 1
    assert found[0].error is None
    assert found[0].cls is not None
    assert found[0].cls.manifest.id == "roku"


def test_roku_is_not_an_entry_point() -> None:
    names = {ep.name for ep in importlib.metadata.entry_points(group="netview.plugins")}
    assert "roku" not in names


def test_plugin_loads_with_permissions(make_client: Make) -> None:
    client = make_client()
    listed = {p["id"]: p for p in client.get("/api/v1/plugins").json()}
    assert listed["roku"]["state"] == "active"
    assert listed["roku"]["name"] == "Roku"
    assert "network:control" in listed["roku"]["permissions"]
    assert listed["roku"]["ui_module"] == "/plugins/roku/static/ui.js"
    assert client.get("/plugins/roku/static/ui.js").status_code == 200


def test_empty_list_then_put_document_then_list(make_client: Make, transport: FakeTransport) -> None:
    client = make_client()
    body = client.get(f"{BASE}/tvs").json()
    assert body["tvs"] == []
    assert body["scan"]["running"] is False
    assert client.get(f"{BASE}/tvs/document").json()["schema"] == "netview.roku/tvs@1"
    tv_id = save_tv(client, transport)
    assert client.get(f"{BASE}/tvs").json()["tvs"][0]["id"] == tv_id
    assert client.get(f"{BASE}/tvs/document").json()["tvs"][0]["ip"] == TV_IP


def test_put_document_error_is_422_with_message(make_client: Make) -> None:
    response = make_client().put(f"{BASE}/tvs/document", json={"text": "not json"})
    assert response.status_code == 422
    assert response.json()["error"]


def test_scan_202_then_409_while_running(make_client: Make, transport: FakeTransport) -> None:
    client = make_client()
    transport.tvs["192.168.1.77"] = ON
    gate = threading.Event()
    transport.gate = gate
    try:
        response = client.post(f"{BASE}/scan")
        assert response.status_code == 202
        assert response.json() == {"started": True}
        assert transport.entered.wait(10)
        assert client.get(f"{BASE}/scan").json()["running"] is True
        again = client.post(f"{BASE}/scan")
        assert again.status_code == 409
        assert again.json() == {"error": "scan already running"}
    finally:
        gate.set()


def test_key_press_reaches_tv_and_bad_key_is_422(make_client: Make, transport: FakeTransport) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    assert client.post(f"{BASE}/tvs/{tv_id}/key/Home").json() == {"ok": True}
    assert client.post(f"{BASE}/tvs/{tv_id}/key/VolumeUp?action=down").status_code == 200
    assert transport.posts == ["/keypress/Home", "/keydown/VolumeUp"]
    bad = client.post(f"{BASE}/tvs/{tv_id}/key/NotAKey")
    assert bad.status_code == 422
    assert bad.json()["error"]


def test_launch_and_text(make_client: Make, transport: FakeTransport) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    assert client.post(f"{BASE}/tvs/{tv_id}/launch/12").json() == {"ok": True}
    assert client.post(f"{BASE}/tvs/{tv_id}/text", json={"text": "hi"}).json() == {"ok": True}
    assert transport.posts[0] == "/launch/12"
    assert transport.posts[1:] == ["/keypress/Lit_h", "/keypress/Lit_i"]
    assert client.post(f"{BASE}/tvs/{tv_id}/launch/not-an-app").status_code == 422
    assert client.post(f"{BASE}/tvs/{tv_id}/refresh").status_code == 202


def test_icon_is_served_with_the_tvs_content_type(make_client: Make, transport: FakeTransport) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    response = client.get(f"{BASE}/tvs/{tv_id}/icon/12")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG


def test_command_to_limited_tv_is_502_with_limited_message(
    make_client: Make, transport: FakeTransport
) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    transport.limited_commands = True
    response = client.post(f"{BASE}/tvs/{tv_id}/key/Home")
    assert response.status_code == 502
    assert response.json() == {"error": "This TV's Network access setting (Limited) refuses commands"}


def test_unknown_tv_is_404(make_client: Make) -> None:
    client = make_client()
    for response in (
        client.post(f"{BASE}/tvs/nope/key/Home"),
        client.post(f"{BASE}/tvs/nope/launch/12"),
        client.post(f"{BASE}/tvs/nope/text", json={"text": "x"}),
        client.post(f"{BASE}/tvs/nope/refresh"),
        client.get(f"{BASE}/tvs/nope/icon/12"),
    ):
        assert response.status_code == 404
        assert response.json() == {"error": "Unknown TV"}


def test_scripts_are_plain_text_when_present_and_404_otherwise(make_client: Make) -> None:
    client = make_client()
    response = client.get(f"{BASE}/scripts/find_rokus.py")
    if (ROKU_DIR / "static" / "find_rokus.py").is_file():
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
    else:
        assert response.status_code == 404
    assert client.get(f"{BASE}/scripts/other.py").status_code in (404, 405)


def test_writes_need_the_netview_header(make_client: Make, transport: FakeTransport) -> None:
    client = make_client(headers={})
    transport.tvs[TV_IP] = ON
    assert client.post(f"{BASE}/scan").status_code == 403
    assert client.put(f"{BASE}/tvs/document", json={"text": "{}"}).status_code == 403
    assert client.get(f"{BASE}/tvs").status_code == 200


def _plugin(**settings: Any) -> Any:
    plugin = RokuPlugin()
    ctx = SimpleNamespace(
        settings=RokuSettings(**settings),
        unit_of_work=lambda: None,
        log=None,
        clock=None,
        probes=None,
        core=None,
    )
    plugin.setup(ctx)
    return plugin


def test_jobs_follow_auto_scan_setting() -> None:
    def by_name(**settings: Any) -> dict[str, Any]:
        return {j.name: j for j in _plugin(**settings).jobs()}

    never = by_name(auto_scan="never", status_interval_s=10)
    assert set(never) == {"status"}
    assert never["status"].interval_s == 10
    assert never["status"].initial_delay_s == 3
    assert never["status"].timeout_s == 20

    slow = by_name(auto_scan="never", status_interval_s=300)
    assert slow["status"].timeout_s == 60

    startup = by_name(auto_scan="startup")
    assert startup["scan"].interval_s == 10**9
    assert startup["scan"].initial_delay_s == 5
    assert startup["scan"].timeout_s == 120

    every = by_name(auto_scan="startup_and_every", scan_every_h=6)
    assert every["scan"].interval_s == 6 * 3600
    assert every["scan"].initial_delay_s == 5


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("text/html", b"<script>alert(1)</script>"),
        ("image/svg+xml", b"<svg onload='x()'/>"),
        ("text/javascript", b"alert(1)"),
        ("", PNG),
        ("image/png", b"x" * 70000),
        ("image/png", PNG + bytes(200 * 1024)),
        ("image/png", b"<html><script>alert(1)</script></html>"),
        ("image/png", JPEG),
        ("image/jpeg", PNG),
        ("image/gif", WEBP),
        ("image/webp", b"RIFF\x00\x00\x00\x00WAVEfmt "),
        ("image/png", PNG[:4]),
    ],
)
def test_icon_refuses_anything_but_a_small_raster_image(
    make_client: Make, transport: FakeTransport, content_type: str, body: bytes
) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    transport.icon = (content_type, body)
    response = client.get(f"{BASE}/tvs/{tv_id}/icon/12")
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")


def test_icon_content_type_parameters_are_dropped_and_sniffing_is_off(
    make_client: Make, transport: FakeTransport
) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    transport.icon = ("Image/JPEG; charset=binary", JPEG)
    response = client.get(f"{BASE}/tvs/{tv_id}/icon/12")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == CSP


@pytest.mark.parametrize(
    ("content_type", "body"),
    [("image/png", PNG), ("image/jpeg", JPEG), ("image/gif", GIF), ("image/webp", WEBP)],
)
def test_icon_real_images_are_served_with_both_hardening_headers(
    make_client: Make, transport: FakeTransport, content_type: str, body: bytes
) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    transport.icon = (content_type, body)
    response = client.get(f"{BASE}/tvs/{tv_id}/icon/12")
    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.content == body
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == CSP


def test_a_100_kb_icon_is_served_and_may_be_cached_by_the_browser(
    make_client: Make, transport: FakeTransport
) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    big = PNG + bytes(100 * 1024)
    transport.icon = ("image/png", big)
    response = client.get(f"{BASE}/tvs/{tv_id}/icon/12")
    assert response.status_code == 200
    assert response.content == big
    assert response.headers["cache-control"] == "private, max-age=3600"


def test_icon_is_refused_for_a_different_device(make_client: Make, transport: FakeTransport) -> None:
    client = make_client()
    tv_id = save_tv(client, transport)
    document = client.get(f"{BASE}/tvs/document").json()
    document["tvs"][0]["serial"] = "X01234567890"
    assert client.put(f"{BASE}/tvs/document", json={"text": json.dumps(document)}).status_code == 200
    transport.tvs[TV_IP] = ON.replace("X01234567890", "OTHERSERIAL")
    assert "OTHERSERIAL" in transport.tvs[TV_IP]
    response = client.get(f"{BASE}/tvs/{tv_id}/icon/12")
    assert response.status_code == 409
    assert response.json()["error"].startswith("A different Roku, ")


def test_a_settings_save_does_not_restart_a_scan_that_already_ran() -> None:
    plugin = _plugin(auto_scan="startup", scan_every_h=6)
    assert [j.name for j in plugin.jobs()] == ["status", "scan"]
    ran: list[bool] = []
    plugin._service.run_scan = lambda: ran.append(True)
    scan_job = next(j for j in plugin.jobs() if j.name == "scan")
    scan_job.run()
    assert ran == [True]
    assert [j.name for j in plugin.jobs()] == ["status"]


def test_every_mode_waits_a_full_interval_after_the_startup_scan() -> None:
    plugin = _plugin(auto_scan="startup_and_every", scan_every_h=6)
    scan = next(j for j in plugin.jobs() if j.name == "scan")
    assert scan.initial_delay_s == 5
    plugin._service.run_scan = lambda: None
    scan.run()
    again = next(j for j in plugin.jobs() if j.name == "scan")
    assert again.initial_delay_s == 6 * 3600
    assert again.interval_s == 6 * 3600


def test_icon_cache_evicts_oldest_by_total_bytes() -> None:
    cache = routes._IconCache()
    chunk = bytes(100 * 1024)
    count = routes._ICON_CACHE_MAX_BYTES // len(chunk) + 5
    for i in range(count):
        cache.put((f"tv{i}", "1"), chunk, "image/png")
    assert cache.get(("tv0", "1")) is None
    assert cache.get((f"tv{count - 1}", "1")) is not None
    assert cache.total_bytes <= routes._ICON_CACHE_MAX_BYTES
