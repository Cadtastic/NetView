from __future__ import annotations

import http.server
import socket
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import pytest
from netview_local_plugins.roku.ecp import (
    MSG_NOT_ANSWERING,
    ActiveApp,
    App,
    EcpClient,
    EcpError,
    EcpResponse,
    parse_active_app,
    parse_apps,
    parse_device_info,
    urllib_transport,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOT_ANSWERING = "The TV isn't answering. It may be fully powered off or have a new address."


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_device_info_on() -> None:
    d = parse_device_info(read("device-info-on.xml"))
    assert d is not None
    assert (d.serial, d.name, d.model, d.tv, d.mode, d.power) == (
        "X01234567890",
        "Living Room TV",
        "TCL 55S455",
        True,
        "default",
        "on",
    )
    assert d.location == "Living room"
    assert d.power_raw == "PowerOn"


def test_parse_device_info_name_falls_back_to_friendly_then_default() -> None:
    d = parse_device_info(read("device-info-nouser.xml"))
    assert d is not None
    assert d.name == "Roku TV"
    body = (
        b"<device-info><serial-number>S1</serial-number>"
        b"<default-device-name>TCL - 55</default-device-name></device-info>"
    )
    d2 = parse_device_info(body)
    assert d2 is not None
    assert d2.name == "TCL - 55"


def test_parse_device_info_standby_and_limited() -> None:
    standby = parse_device_info(read("device-info-standby.xml"))
    assert standby is not None
    assert standby.power == "standby"
    limited = parse_device_info(read("device-info-limited.xml"))
    assert limited is not None
    assert limited.mode == "limited"


@pytest.mark.parametrize(
    ("raw", "power"),
    [
        ("PowerOn", "on"),
        ("DisplayOff", "standby"),
        ("Ready", "standby"),
        ("Headless", "standby"),
        ("Suspend", "standby"),
        ("Booting", "unknown"),
        ("", "unknown"),
    ],
)
def test_power_mapping(raw: str, power: str) -> None:
    body = f"<device-info><power-mode>{raw}</power-mode></device-info>".encode()
    d = parse_device_info(body)
    assert d is not None
    assert d.power == power


def test_parse_refuses_doctype_and_other_roots() -> None:
    assert parse_device_info(read("doctype.xml")) is None
    assert parse_device_info(read("not-roku.xml")) is None
    assert parse_device_info(b"not xml at all") is None
    assert parse_active_app(read("doctype.xml")) is None
    assert parse_apps(read("doctype.xml")) is None
    assert parse_apps(read("not-roku.xml")) is None


def test_parse_active_app_youtube_and_home() -> None:
    assert parse_active_app(read("active-app-youtube.xml")) == ActiveApp("837", "YouTube", None)
    home = parse_active_app(read("active-app-home.xml"))
    assert home is not None
    assert (home.id, home.name) == (None, "Home")


def test_parse_active_app_screensaver() -> None:
    body = b'<active-app><app>Roku</app><screensaver id="5533" type="ssvr">Sky</screensaver></active-app>'
    a = parse_active_app(body)
    assert a is not None
    assert a.screensaver == "Sky"


def test_parse_apps_keeps_ids_names_types() -> None:
    apps = parse_apps(read("apps.xml"))
    assert apps == [
        App("12", "Netflix", "appl"),
        App("837", "YouTube", "appl"),
        App("tvinput.hdmi1", "HDMI 1", "tvin"),
    ]


class FakeTransport:
    def __init__(self, response: EcpResponse | None = None, error: OSError | None = None) -> None:
        self.response = response or EcpResponse(200, {}, b"")
        self.error = error
        self.calls: list[tuple[str, str, float]] = []

    def __call__(self, method: str, url: str, timeout_s: float) -> EcpResponse:
        self.calls.append((method, url, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


def resp(status: int, body: bytes = b"", headers: Mapping[str, str] | None = None) -> EcpResponse:
    return EcpResponse(status, dict(headers or {}), body)


@pytest.mark.parametrize(
    ("status", "msg"),
    [
        (403, "This TV's Network access setting (Limited) refuses commands"),
        (404, "The TV doesn't know that key or app"),
        (500, "The TV answered 500"),
    ],
)
def test_client_post_maps_status_to_message(status: int, msg: str) -> None:
    client = EcpClient(FakeTransport(resp(status)), 2.0)
    with pytest.raises(EcpError) as exc:
        client.post("192.168.1.60", "/keypress/Home")
    assert exc.value.status == status
    assert exc.value.message == msg


def test_client_post_maps_oserror_to_not_answering() -> None:
    client = EcpClient(FakeTransport(error=TimeoutError("timed out")), 2.0)
    with pytest.raises(EcpError) as exc:
        client.post("192.168.1.60", "/keypress/Home")
    assert exc.value.status is None
    assert exc.value.message == NOT_ANSWERING


def test_client_builds_url_on_port_8060() -> None:
    t = FakeTransport(resp(200))
    EcpClient(t, 1.5).post("192.168.1.60", "/keypress/Home")
    assert t.calls == [("POST", "http://192.168.1.60:8060/keypress/Home", 1.5)]


def test_client_reads_device_info_active_app_apps_icon() -> None:
    ip = "192.168.1.60"
    t = FakeTransport(resp(200, read("device-info-on.xml")))
    assert EcpClient(t, 2.0).device_info(ip).name == "Living Room TV"
    assert t.calls[0][:2] == ("GET", "http://192.168.1.60:8060/query/device-info")
    t = FakeTransport(resp(200, read("active-app-youtube.xml")))
    assert EcpClient(t, 2.0).active_app(ip).name == "YouTube"
    assert t.calls[0][1].endswith("/query/active-app")
    t = FakeTransport(resp(200, read("apps.xml")))
    assert len(EcpClient(t, 2.0).apps(ip)) == 3
    assert t.calls[0][1].endswith("/query/apps")
    t = FakeTransport(resp(200, b"\x89PNG", {"Content-Type": "image/png"}))
    assert EcpClient(t, 2.0).icon(ip, "837") == (b"\x89PNG", "image/png")
    assert t.calls[0][1].endswith("/query/icon/837")


def test_client_unparsable_answer_is_an_error() -> None:
    client = EcpClient(FakeTransport(resp(200, read("not-roku.xml"))), 2.0)
    with pytest.raises(EcpError):
        client.device_info("192.168.1.60")


def test_device_info_4xx_with_roku_server_header_is_blank_roku() -> None:
    client = EcpClient(FakeTransport(resp(403, b"", {"Server": "Roku/12.5.0 UPnP/1.0"})), 2.0)
    d = client.device_info("192.168.1.60")
    assert (d.serial, d.name, d.model, d.location, d.mode, d.power_raw) == ("", "", "", "", "", "")
    assert d.tv is False
    assert d.power == "unknown"


def test_device_info_4xx_without_roku_header_is_an_error() -> None:
    client = EcpClient(FakeTransport(resp(403, b"", {"Server": "nginx"})), 2.0)
    with pytest.raises(EcpError):
        client.device_info("192.168.1.60")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"<device-info/>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Test", "yes")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_urllib_transport_against_local_server_returns_status_and_body() -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/query/device-info"
        got = urllib_transport("GET", url, 2.0)
        assert got.status == 200
        assert got.body == b"<device-info/>"
        assert got.headers["x-test"] == "yes"
        posted = urllib_transport("POST", url, 2.0)
        assert posted.status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_urllib_transport_refused_raises_oserror() -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    server.server_close()
    with pytest.raises(OSError):
        urllib_transport("GET", f"http://127.0.0.1:{port}/x", 1.0)


def _non_http_server() -> tuple[socket.socket, threading.Thread]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def serve() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                conn.recv(1024)
                conn.sendall(b"SSH-2.0-OpenSSH_9.0\r\n")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return listener, thread


def test_urllib_transport_turns_a_non_http_answer_into_oserror() -> None:
    listener, thread = _non_http_server()
    try:
        port = listener.getsockname()[1]
        with pytest.raises(OSError):
            urllib_transport("GET", f"http://127.0.0.1:{port}/query/device-info", 2.0)
    finally:
        listener.close()
        thread.join(timeout=2)


def test_client_reports_a_non_http_service_as_not_answering() -> None:
    listener, thread = _non_http_server()
    try:
        port = listener.getsockname()[1]

        def transport(method: str, url: str, timeout_s: float) -> EcpResponse:
            local = f"http://127.0.0.1:{port}" + url.split(":8060", 1)[1]
            return urllib_transport(method, local, timeout_s)

        with pytest.raises(EcpError) as err:
            EcpClient(transport, 2.0).device_info("192.168.1.60")
        assert err.value.message == MSG_NOT_ANSWERING
    finally:
        listener.close()
        thread.join(timeout=2)


DEVICE_INFO = "<device-info><serial-number>S1</serial-number></device-info>"
EVIL_DOCTYPE = '<!DOCTYPE device-info [<!ENTITY a "x">]>'


def test_utf16_body_with_a_doctype_is_refused() -> None:
    body = ("<?xml version='1.0' encoding='utf-16'?>" + EVIL_DOCTYPE + DEVICE_INFO).encode("utf-16")
    assert parse_device_info(body) is None
    assert parse_apps(body) is None
    assert parse_active_app(body) is None


def test_doctype_after_a_long_comment_is_refused() -> None:
    body = ("<!--" + "x" * 5000 + "-->" + EVIL_DOCTYPE + DEVICE_INFO).encode()
    assert len(body) > 5000
    assert parse_device_info(body) is None


def test_plain_xml_still_parses_with_the_strict_parser() -> None:
    d = parse_device_info(("<?xml version='1.0' encoding='UTF-8' ?>" + DEVICE_INFO).encode())
    assert d is not None and d.serial == "S1"
    utf16 = parse_device_info(DEVICE_INFO.encode("utf-16"))
    assert utf16 is not None and utf16.serial == "S1"


class _Trickle(http.server.BaseHTTPRequestHandler):
    status = 200

    def do_GET(self) -> None:
        self.send_response(self.status)
        self.send_header("Content-Length", "1000")
        self.end_headers()
        try:
            for _ in range(1000):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.2)
        except OSError:
            pass

    def log_message(self, format: str, *args: object) -> None:
        pass


class _TrickleError(_Trickle):
    status = 404


def _deadline_holds(handler: type[http.server.BaseHTTPRequestHandler]) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/query/apps"
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            urllib_transport("GET", url, 1.0)
        assert time.monotonic() - started < 1.5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_urllib_transport_enforces_one_deadline_against_a_slow_drip() -> None:
    _deadline_holds(_Trickle)


def test_urllib_transport_enforces_the_deadline_on_an_error_body_too() -> None:
    _deadline_holds(_TrickleError)
