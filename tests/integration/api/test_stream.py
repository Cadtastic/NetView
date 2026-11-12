"""SSE needs a real socket: TestClient buffers a response until the app has finished it."""

import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from api_helpers import ApiWorld, make_app

from netview.domain.events import DomainEvent, EventKind


@pytest.fixture
def live_url(world: ApiWorld) -> Iterator[str]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(make_app(world), log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_stream_emits_domain_event(world: ApiWorld, live_url: str) -> None:
    deadline = time.time() + 2
    with (
        httpx.Client(timeout=5, cookies={"netview_session": world.session_token()}) as http,
        http.stream("GET", f"{live_url}/api/v1/stream") as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        world.bus.publish(DomainEvent(EventKind.NICKNAME, "nickname set", 123, "192.168.1.5", "k"))
        lines: list[str] = []
        for line in response.iter_lines():
            lines.append(line)
            if line.startswith("data:"):
                break
            assert time.time() < deadline
    assert "event: domain" in lines
    data = next(line for line in lines if line.startswith("data:"))
    assert '"kind":"nickname"' in data.replace(" ", "")
