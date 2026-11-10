"""Review fix I5: /stream sends a coalesced ``state`` frame after job runs and scans."""

import json
import time

import httpx
from api_helpers import ApiWorld, make_app, make_client
from test_stream import live_url  # noqa: F401  (fixture)


def test_stream_sends_state_frame_after_a_job_finishes(world: ApiWorld, live_url: str) -> None:  # noqa: F811
    with httpx.Client(timeout=5) as http, http.stream("GET", f"{live_url}/api/v1/stream") as response:
        world.notifier.state_changed()  # what bootstrap wires to the scheduler's on_job_finished
        lines: list[str] = []
        deadline = time.time() + 3
        for line in response.iter_lines():
            lines.append(line)
            if line.startswith("data:"):
                break
            assert time.time() < deadline
    assert "event: state" in lines
    payload = json.loads(next(line for line in lines if line.startswith("data:"))[5:])
    assert set(payload) == {"t_ms"}
    assert abs(payload["t_ms"] - time.time() * 1000) < 5000


def test_state_frames_are_coalesced_to_one_per_second(world: ApiWorld, live_url: str) -> None:  # noqa: F811
    count = 0
    started = time.time()
    # the stream goes quiet after the burst, so a read timeout marks the end of the window
    with (
        httpx.Client(timeout=httpx.Timeout(5, read=2.0)) as http,
        http.stream("GET", f"{live_url}/api/v1/stream") as response,
    ):
        for _ in range(10):
            world.notifier.state_changed()
        try:
            for line in response.iter_lines():
                if line.startswith("event: state"):
                    count += 1
        except httpx.ReadTimeout:
            pass
    # one immediately and one trailing frame for the burst; never ten
    assert 1 <= count <= 2
    assert time.time() - started < 6


def test_post_scan_signals_a_state_change(world: ApiWorld) -> None:
    hits: list[int] = []
    world.notifier.subscribe(lambda: hits.append(1))
    client = make_client(make_app(world))
    response = client.post("/api/v1/scan")
    assert response.status_code in (200, 409)  # no discovery provider in this world
    assert hits  # signalled even though the scan could not run
