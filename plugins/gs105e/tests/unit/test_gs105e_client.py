"""Switch session and transport tests."""

from __future__ import annotations

import gzip
import http.client
import socket
import threading
from pathlib import Path

import pytest
from netview_local_plugins.gs105e.auth import login_hash
from netview_local_plugins.gs105e.client import (
    MAX_BODY,
    AuthFailed,
    MalformedReply,
    RequestClock,
    SessionLost,
    SwitchSession,
    Unreachable,
    UnsupportedSwitch,
    http_fetch,
)
from netview_local_plugins.gs105e.pages import PageChanged
from netview_local_plugins.gs105e.tools.fake_switch import FakeSwitch

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "fw-1.6.0.11"


def make(password: str = "secret", gap_s: float = 0.0) -> tuple[SwitchSession, FakeSwitch, list[float]]:
    fake = FakeSwitch(FIX)
    sleeps: list[float] = []
    clock = [0.0]
    session = SwitchSession(
        "sw", 80, password, fake, gap_s=gap_s, sleep=sleeps.append, monotonic=lambda: clock[0]
    )
    return session, fake, sleeps


def test_login_posts_hash() -> None:
    session, fake, _ = make()
    page = session.login()
    assert session.logged_in
    assert page.rand == "12345678"
    assert fake.bodies[1] == b"password=" + login_hash("secret", "12345678").encode()
    assert fake.request_headers[1]["Content-Type"] == "application/x-www-form-urlencoded"
    assert fake.requests == [("GET", "/login.cgi"), ("POST", "/login.cgi")]


def test_wrong_password() -> None:
    session, _, _ = make("nope")
    with pytest.raises(AuthFailed):
        session.login()
    assert not session.logged_in


def test_other_device() -> None:
    session, fake, _ = make()
    fake.override["/login.cgi"] = (FIX / "login.cgi").read_text().replace("GS105Ev2", "Other")
    with pytest.raises(UnsupportedSwitch):
        session.login()


def test_get_returns_fixture() -> None:
    session, _, _ = make()
    session.login()
    assert session.get("/status.cgi") == (FIX / "status.cgi").read_bytes().decode("utf-8", errors="replace")


def test_session_lost() -> None:
    session, fake, _ = make()
    session.login()
    fake.drop_sessions()
    with pytest.raises(SessionLost):
        session.get("/status.cgi")


def test_down_hides_password() -> None:
    session, fake, _ = make()
    fake.down = True
    with pytest.raises(Unreachable) as info:
        session.login()
    assert "secret" not in str(info.value)


def test_gap() -> None:
    fake = FakeSwitch(FIX)
    sleeps: list[float] = []
    clock = [0.0]
    session = SwitchSession(
        "sw", 80, "secret", fake, gap_s=0.2, sleep=sleeps.append, monotonic=lambda: clock[0]
    )
    session.login()
    assert sleeps and sleeps[0] == pytest.approx(0.2)


def test_logout_never_raises() -> None:
    session, fake, _ = make()
    session.login()
    fake.down = True
    session.logout()
    assert not session.logged_in


class _Server:
    def __init__(self, reply: bytes) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port: int = self.sock.getsockname()[1]
        self.reply = reply
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(2)
            try:
                conn.recv(4096)
                conn.sendall(self.reply)
            except OSError:
                pass

    def close(self) -> None:
        self.sock.close()
        self.thread.join(timeout=3)


def test_http_fetch_gunzips() -> None:
    payload = gzip.compress(b"<html>hi</html>")
    head = f"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
    server = _Server(head + payload)
    try:
        status, headers, body = http_fetch("127.0.0.1", server.port, "GET", "/x", None, {}, 3.0)
    finally:
        server.close()
    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert body == b"<html>hi</html>"


def test_http_fetch_bare_gzip_is_malformed() -> None:
    server = _Server(gzip.compress(b"<html>hi</html>"))
    try:
        with pytest.raises(MalformedReply):
            http_fetch("127.0.0.1", server.port, "GET", "/x", None, {}, 3.0)
    finally:
        server.close()


def _gzip_reply(payload: bytes) -> bytes:
    head = f"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
    return head + payload


def _fetch_reply(reply: bytes) -> None:
    server = _Server(reply)
    try:
        http_fetch("127.0.0.1", server.port, "GET", "/x", None, {}, 3.0)
    finally:
        server.close()


def test_http_fetch_corrupt_gzip_is_malformed() -> None:
    good = gzip.compress(b"<html>" + b"hello " * 200 + b"</html>")
    corrupt = good[:20] + bytes(b ^ 0xFF for b in good[20:40]) + good[40:]
    with pytest.raises(MalformedReply):
        _fetch_reply(_gzip_reply(corrupt))


def test_http_fetch_truncated_gzip_is_malformed() -> None:
    good = gzip.compress(b"<html>" + b"hello " * 200 + b"</html>")
    with pytest.raises(MalformedReply):
        _fetch_reply(_gzip_reply(good[:-12]))


def test_http_fetch_gzip_bomb_is_malformed() -> None:
    with pytest.raises(MalformedReply):
        _fetch_reply(_gzip_reply(gzip.compress(bytes(MAX_BODY + 1024))))


def test_dropped_connection_is_oserror() -> None:
    with pytest.raises(OSError) as info:
        _fetch_reply(b"")
    assert not isinstance(info.value, MalformedReply)


def test_session_reports_remote_disconnect_as_unreachable() -> None:
    def fetch(*args: object) -> tuple[int, dict[str, str], bytes]:
        raise http.client.RemoteDisconnected("closed")

    session = SwitchSession("sw", 80, "secret", fetch, gap_s=0.0, sleep=lambda _: None)
    with pytest.raises(Unreachable):
        session.login()


def test_tick_may_drop_sessions() -> None:
    session, fake, _ = make()
    session.login()
    fake.tick = fake.drop_sessions
    session.get("/portStatistics.cgi")  # the read that ticks still succeeds
    with pytest.raises(SessionLost):
        session.get("/status.cgi")


# ---- final review fixes ----------------------------------------------------------------------


def _login_page_fetch(post: object) -> object:
    """A fetch that serves the fixture login page and hands the login POST to ``post``."""
    page = (FIX / "login.cgi").read_bytes()

    def fetch(
        host: str, port: int, method: str, path: str, body: bytes | None, headers: object, timeout_s: float
    ) -> tuple[int, dict[str, str], bytes]:
        if method == "GET":
            return 200, {}, page
        return post(host, port, method, path, body, headers, timeout_s)  # type: ignore[operator, no-any-return]

    return fetch


def test_http_fetch_joins_repeated_set_cookie_headers() -> None:
    reply = (
        b"HTTP/1.1 200 OK\r\nSet-Cookie: SID=abc; PATH=/\r\nSet-Cookie: lang=en\r\nContent-Length: 0\r\n\r\n"
    )
    server = _Server(reply)
    try:
        _, headers, _ = http_fetch("127.0.0.1", server.port, "GET", "/x", None, {}, 3.0)
    finally:
        server.close()
    assert headers["set-cookie"] == "SID=abc; PATH=/\nlang=en"


def test_login_with_a_second_cookie_after_sid() -> None:
    def post(*args: object) -> tuple[int, dict[str, str], bytes]:
        return 200, {"set-cookie": "SID=abc; PATH=/\nlang=en"}, b""

    session = SwitchSession("sw", 80, "secret", _login_page_fetch(post), gap_s=0.0, sleep=lambda _: None)  # type: ignore[arg-type]
    session.login()
    assert session.logged_in


def test_http_fetch_empty_gzip_labelled_body_is_empty() -> None:
    server = _Server(
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nSet-Cookie: SID=abc\r\nContent-Length: 0\r\n\r\n"
    )
    try:
        status, headers, body = http_fetch("127.0.0.1", server.port, "GET", "/x", None, {}, 3.0)
    finally:
        server.close()
    assert (status, body) == (200, b"")
    assert headers["set-cookie"] == "SID=abc"


def test_login_with_an_empty_gzip_labelled_reply_logs_in() -> None:
    server = _Server(
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nSet-Cookie: SID=abc\r\nContent-Length: 0\r\n\r\n"
    )

    def post(host: str, port: int, method: str, path: str, body: object, headers: object, t: float) -> object:
        return http_fetch("127.0.0.1", server.port, method, path, None, {}, t)

    try:
        session = SwitchSession("sw", 80, "secret", _login_page_fetch(post), gap_s=0.0, sleep=lambda _: None)  # type: ignore[arg-type]
        session.login()
    finally:
        server.close()
    assert session.logged_in


def test_malformed_gzip_reply_keeps_its_headers() -> None:
    good = gzip.compress(b"<html>" + b"hello " * 200 + b"</html>")
    size = len(good) - 12
    head = (
        f"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nSet-Cookie: SID=abc\r\nContent-Length: {size}\r\n\r\n"
    )
    server = _Server(head.encode() + good[:-12])
    try:
        with pytest.raises(MalformedReply) as info:
            http_fetch("127.0.0.1", server.port, "GET", "/x", None, {}, 3.0)
    finally:
        server.close()
    assert info.value.headers["set-cookie"] == "SID=abc"


def test_login_uses_the_cookie_of_a_malformed_reply() -> None:
    def post(*args: object) -> tuple[int, dict[str, str], bytes]:
        raise MalformedReply("bad gzip body", {"set-cookie": "SID=abc"})

    session = SwitchSession("sw", 80, "secret", _login_page_fetch(post), gap_s=0.0, sleep=lambda _: None)  # type: ignore[arg-type]
    session.login()
    assert session.logged_in


def test_login_with_a_malformed_reply_and_no_cookie_is_page_changed() -> None:
    def post(*args: object) -> tuple[int, dict[str, str], bytes]:
        raise MalformedReply("bad gzip body")

    session = SwitchSession("sw", 80, "secret", _login_page_fetch(post), gap_s=0.0, sleep=lambda _: None)  # type: ignore[arg-type]
    with pytest.raises(PageChanged):
        session.login()
    assert not session.logged_in


def test_gap_carries_over_to_a_fresh_session() -> None:
    fake = FakeSwitch(FIX)
    sleeps: list[float] = []
    clock = [0.0]
    shared = RequestClock()
    first = SwitchSession(
        "sw",
        80,
        "secret",
        fake,
        gap_s=0.2,
        sleep=sleeps.append,
        monotonic=lambda: clock[0],
        request_clock=shared,
    )
    first.login()
    sleeps.clear()
    second = SwitchSession(
        "sw",
        80,
        "secret",
        fake,
        gap_s=0.2,
        sleep=sleeps.append,
        monotonic=lambda: clock[0],
        request_clock=shared,
    )
    second.logout()
    assert sleeps == [pytest.approx(0.2)]
