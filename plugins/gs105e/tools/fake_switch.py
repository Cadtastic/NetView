"""A stand-in GS105Ev2 that serves saved pages, for tests and browser checks.

Usage:
    python -I fake_switch.py [--port 8105] [--fixtures DIR] [--password secret]

Serves the pages of a fixture folder on 127.0.0.1 the way the switch does: every page answers 200, with the
"Redirect to Login" page unless the request carries the SID cookie a good login sets. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import zip_longest
from pathlib import Path
from threading import Lock

RAND = "12345678"
DEFAULT_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "fw-1.6.0.11"
_STATISTICS = "/portStatistics.cgi"


def _login_hash(password: str, rand: str) -> str:
    # same algorithm as the plugin's auth.login_hash, repeated so this file also runs as a plain script
    merged = "".join(x + y for x, y in zip_longest(password, rand, fillvalue=""))
    return hashlib.md5(merged.encode("utf-8")).hexdigest()


class FakeSwitch:
    """A ``Fetch``-compatible callable that behaves like a GS105Ev2's web interface."""

    def __init__(self, fixtures: Path, password: str = "secret") -> None:
        self.fixtures = fixtures
        self.password = password
        self.requests: list[tuple[str, str]] = []
        self.down = False
        self.override: dict[str, str] = {}
        self.tick: Callable[[], None] | None = None
        self._sessions: set[str] = set()
        self._count = 0
        self._lock = Lock()

    def drop_sessions(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _page(self, name: str) -> bytes:
        return (self.fixtures / name).read_bytes()

    def __call__(
        self,
        host: str,
        port: int,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        if self.down:
            raise OSError("switch is down")
        path = path.split("?", 1)[0]
        with self._lock:
            self.requests.append((method, path))
            return self._answer(method, path, body, headers)

    def _sid(self, headers: Mapping[str, str]) -> str | None:
        for key, value in headers.items():
            if key.lower() == "cookie":
                for part in value.split(";"):
                    name, _, sid = part.strip().partition("=")
                    if name == "SID":
                        return sid
        return None

    def _answer(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> tuple[int, Mapping[str, str], bytes]:
        html = {"content-type": "text/html"}
        if path == "/login.cgi":
            if method == "POST":
                expected = f"password={_login_hash(self.password, RAND)}".encode()
                if body == expected:
                    self._count += 1
                    sid = f"s{self._count}"
                    self._sessions.add(sid)
                    return 200, {**html, "set-cookie": f"SID={sid}; PATH=/"}, self._page("login.cgi")
                return 200, html, self._page("login.cgi")
            return 200, html, self._text(path, "login.cgi")
        cookie = self._sid(headers)
        if cookie is None or cookie not in self._sessions:
            return 200, html, self._page("logged_out.html")
        if path == "/logout.cgi":
            self._sessions.discard(cookie)
            return 200, html, self._page("logged_out.html")
        if path == _STATISTICS and self.tick is not None:
            self.tick()
        name = path.lstrip("/")
        if path in self.override or (self.fixtures / name).is_file():
            return 200, html, self._text(path, name)
        return 404, html, b"not found"

    def _text(self, path: str, name: str) -> bytes:
        if path in self.override:
            return self.override[path].encode("utf-8")
        return self._page(name)


def serve(switch: FakeSwitch, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _run(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            try:
                status, headers, data = switch(
                    "127.0.0.1", port, method, self.path, body, dict(self.headers), 8.0
                )
            except OSError:
                self.send_error(503)
                return
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._run("GET")

        def do_POST(self) -> None:
            self._run("POST")

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve saved GS105Ev2 pages as a fake switch on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8105)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES, help="folder of saved pages")
    parser.add_argument("--password", default="secret")
    args = parser.parse_args()
    server = serve(FakeSwitch(args.fixtures, args.password), args.port)
    print(f"fake GS105E on http://127.0.0.1:{args.port}/ (password {args.password!r})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
