"""Switch session and transport tests."""

from __future__ import annotations

import gzip
import socket
import threading
from pathlib import Path

import pytest
from netview_local_plugins.gs105e.auth import login_hash
from netview_local_plugins.gs105e.client import (
    AuthFailed,
    MalformedReply,
    SessionLost,
    SwitchSession,
    Unreachable,
    UnsupportedSwitch,
    http_fetch,
)
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
    assert login_hash("secret", "12345678")  # sanity
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
