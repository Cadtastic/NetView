"""Roku External Control Protocol (ECP) client: plain HTTP on port 8060, parsed defensively."""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

ECP_PORT = 8060
DEFAULT_TIMEOUT_S = 2.0
MAX_RESPONSE_BYTES = 262144
_DOCTYPE_SCAN_BYTES = 4096

MSG_LIMITED = "This TV's Network access setting (Limited) refuses commands"
MSG_UNKNOWN_KEY = "The TV doesn't know that key or app"
MSG_NOT_ANSWERING = "The TV isn't answering. It may be fully powered off or have a new address."
MSG_NOT_ROKU = "The device answered, but not like a Roku"

_STANDBY = frozenset({"DisplayOff", "Ready", "Headless", "Suspend"})


@dataclass(frozen=True)
class EcpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


# method, url, timeout in seconds; raises OSError on timeout or refusal.
Transport = Callable[[str, str, float], EcpResponse]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


# Talk to LAN addresses directly: never through an HTTP proxy from the environment, never via redirects.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def urllib_transport(method: str, url: str, timeout_s: float) -> EcpResponse:
    request = urllib.request.Request(url, data=b"" if method == "POST" else None, method=method)
    try:
        with _OPENER.open(request, timeout=timeout_s) as resp:
            return EcpResponse(
                resp.status,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.read(MAX_RESPONSE_BYTES),
            )
    except urllib.error.HTTPError as err:
        try:
            body = err.read(MAX_RESPONSE_BYTES)
        except OSError:
            body = b""
        return EcpResponse(err.code, {k.lower(): v for k, v in err.headers.items()}, body)
    except urllib.error.URLError as err:
        raise OSError(str(err.reason)) from err


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    name: str
    model: str
    location: str
    tv: bool
    mode: str
    power_raw: str

    @property
    def power(self) -> Literal["on", "standby", "unknown"]:
        if self.power_raw == "PowerOn":
            return "on"
        if self.power_raw in _STANDBY:
            return "standby"
        return "unknown"


@dataclass(frozen=True)
class ActiveApp:
    id: str | None
    name: str
    screensaver: str | None


@dataclass(frozen=True)
class App:
    id: str
    name: str
    type: str


def _parse_root(body: bytes, tag: str) -> ET.Element | None:
    upper = body[:_DOCTYPE_SCAN_BYTES].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    return root if root.tag == tag else None


def _text(root: ET.Element, tag: str) -> str:
    el = root.find(tag)
    return (el.text or "").strip() if el is not None else ""


def parse_device_info(body: bytes) -> DeviceInfo | None:
    root = _parse_root(body, "device-info")
    if root is None:
        return None
    name = (
        _text(root, "user-device-name")
        or _text(root, "friendly-device-name")
        or _text(root, "default-device-name")
    )
    return DeviceInfo(
        serial=_text(root, "serial-number"),
        name=name,
        model=_text(root, "model-name"),
        location=_text(root, "user-device-location"),
        tv=_text(root, "is-tv") == "true",
        mode=_text(root, "ecp-setting-mode").lower(),
        power_raw=_text(root, "power-mode"),
    )


def parse_active_app(body: bytes) -> ActiveApp | None:
    root = _parse_root(body, "active-app")
    if root is None:
        return None
    saver = root.find("screensaver")
    screensaver = ((saver.text or "").strip() or None) if saver is not None else None
    app = root.find("app")
    app_id = app.get("id") if app is not None else None
    if app is None or not app_id:
        return ActiveApp(None, "Home", screensaver)
    return ActiveApp(app_id, (app.text or "").strip(), screensaver)


def parse_apps(body: bytes) -> list[App] | None:
    root = _parse_root(body, "apps")
    if root is None:
        return None
    return [
        App(app_id, (el.text or "").strip(), el.get("type") or "")
        for el in root.findall("app")
        if (app_id := el.get("id"))
    ]


class EcpError(Exception):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _message_for(status: int) -> str:
    if status == 403:
        return MSG_LIMITED
    if status == 404:
        return MSG_UNKNOWN_KEY
    return f"The TV answered {status}"


def _header(response: EcpResponse, name: str) -> str:
    wanted = name.lower()
    for key, value in response.headers.items():
        if key.lower() == wanted:
            return value
    return ""


class EcpClient:
    def __init__(self, transport: Transport, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._transport = transport
        self._timeout_s = timeout_s

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    @timeout_s.setter
    def timeout_s(self, value: float) -> None:
        self._timeout_s = value

    def _send(self, method: str, ip: str, path: str) -> EcpResponse:
        url = f"http://{ip}:{ECP_PORT}{path}"
        try:
            return self._transport(method, url, self._timeout_s)
        except OSError as err:
            raise EcpError(None, MSG_NOT_ANSWERING) from err

    def _ok(self, method: str, ip: str, path: str) -> EcpResponse:
        response = self._send(method, ip, path)
        if not 200 <= response.status < 300:
            raise EcpError(response.status, _message_for(response.status))
        return response

    def device_info(self, ip: str) -> DeviceInfo:
        response = self._send("GET", ip, "/query/device-info")
        if 400 <= response.status < 500 and "roku" in _header(response, "server").lower():
            # ECP answered but refused device-info (Limited): still a Roku, with nothing known about it.
            return DeviceInfo("", "", "", "", False, "", "")
        if not 200 <= response.status < 300:
            raise EcpError(response.status, _message_for(response.status))
        info = parse_device_info(response.body)
        if info is None:
            raise EcpError(response.status, MSG_NOT_ROKU)
        return info

    def active_app(self, ip: str) -> ActiveApp:
        response = self._ok("GET", ip, "/query/active-app")
        active = parse_active_app(response.body)
        if active is None:
            raise EcpError(response.status, MSG_NOT_ROKU)
        return active

    def apps(self, ip: str) -> list[App]:
        response = self._ok("GET", ip, "/query/apps")
        apps = parse_apps(response.body)
        if apps is None:
            raise EcpError(response.status, MSG_NOT_ROKU)
        return apps

    def icon(self, ip: str, app_id: str) -> tuple[bytes, str]:
        response = self._ok("GET", ip, f"/query/icon/{app_id}")
        return response.body, _header(response, "content-type")

    def post(self, ip: str, path: str) -> None:
        self._ok("POST", ip, path)
