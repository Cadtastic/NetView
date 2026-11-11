"""HTTP session with a GS105Ev2 web interface, and the real transport under it."""

from __future__ import annotations

import contextlib
import gzip
import http.client
import time
from collections.abc import Callable, Mapping

from .auth import login_hash
from .pages import LOGIN, LOGOUT, LoginPage, PageChanged, is_login_page, parse_login

MAX_BODY = 1 << 20
FORM = "application/x-www-form-urlencoded"

Fetch = Callable[
    [str, int, str, str, bytes | None, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]
]


class SwitchError(Exception):
    """Base of the errors a session raises on purpose."""


class Unreachable(SwitchError):
    """The switch did not answer on the network."""


class AuthFailed(SwitchError):
    """The switch refused the password."""


class UnsupportedSwitch(SwitchError):
    """The device is not a GS105E."""


class SessionLost(SwitchError):
    """The switch asked to log in again."""


class MalformedReply(Exception):
    """The switch's reply was not valid HTTP."""


def http_fetch(
    host: str,
    port: int,
    method: str,
    path: str,
    body: bytes | None,
    headers: Mapping[str, str],
    timeout_s: float,
) -> tuple[int, Mapping[str, str], bytes]:
    """The real transport: one request per connection, gzip accepted and undone."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
    try:
        sent = {"Accept-Encoding": "gzip", "Connection": "close", **headers}
        conn.request(method, path, body, sent)
        response = conn.getresponse()
        data = response.read(MAX_BODY)
        reply = {k.lower(): v for k, v in response.getheaders()}
        if reply.get("content-encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError) as exc:
                raise MalformedReply("bad gzip body") from exc
        return response.status, reply, data
    except http.client.HTTPException as exc:
        raise MalformedReply(type(exc).__name__) from exc
    finally:
        conn.close()


def _sid(set_cookie: str) -> str | None:
    for part in set_cookie.replace("\n", ",").split(","):
        first = part.strip().split(";", 1)[0]
        name, _, value = first.partition("=")
        if name.strip() == "SID" and value.strip():
            return value.strip()
    return None


class SwitchSession:
    """One logged-in conversation with the switch, one request at a time."""

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        fetch: Fetch,
        *,
        timeout_s: float = 8.0,
        gap_s: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._fetch = fetch
        self._timeout_s = timeout_s
        self._gap_s = gap_s
        self._sleep = sleep
        self._monotonic = monotonic
        self._last: float | None = None
        self._sid: str | None = None

    @property
    def logged_in(self) -> bool:
        return self._sid is not None

    def _request(
        self, method: str, path: str, body: bytes | None = None, headers: Mapping[str, str] | None = None
    ) -> tuple[int, Mapping[str, str], bytes]:
        if self._last is not None:
            wait = self._gap_s - (self._monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
        sent = dict(headers or {})
        if self._sid is not None:
            sent["Cookie"] = f"SID={self._sid}"
        try:
            return self._fetch(self._host, self._port, method, path, body, sent, self._timeout_s)
        except OSError as exc:
            raise Unreachable(type(exc).__name__) from None
        finally:
            self._last = self._monotonic()

    def _text(
        self,
        path: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, Mapping[str, str], str]:
        try:
            status, reply, data = self._request(method, path, body, headers)
        except MalformedReply:
            raise PageChanged(path, "malformed reply") from None
        return status, reply, data.decode("utf-8", errors="replace")

    def login(self) -> LoginPage:
        self._sid = None
        status, _, text = self._text(LOGIN)
        if status != 200:
            raise PageChanged(LOGIN, f"HTTP {status}")
        try:
            page = parse_login(text)
        except PageChanged:
            raise UnsupportedSwitch("no login challenge") from None
        if "GS105E" not in page.title:
            raise UnsupportedSwitch(page.title)
        form = f"password={login_hash(self._password, page.rand)}".encode("ascii")
        _, reply, _ = self._text(LOGIN, "POST", form, {"Content-Type": FORM})
        sid = _sid(reply.get("set-cookie", ""))
        if sid is None:
            raise AuthFailed("login refused")
        self._sid = sid
        return page

    def get(self, path: str) -> str:
        status, _, text = self._text(path)
        if is_login_page(text):
            self._sid = None
            raise SessionLost(path)
        if status != 200:
            raise PageChanged(path, f"HTTP {status}")
        return text

    def logout(self) -> None:
        with contextlib.suppress(Exception):  # best effort
            self._request("GET", LOGOUT)
        self._sid = None
