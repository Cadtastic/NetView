from api_helpers import ApiWorld
from fastapi.testclient import TestClient


def test_since_ms_returns_only_newer_points(world: ApiWorld, client: TestClient) -> None:
    for t in (1, 2, 3):
        world.metrics.append("health.gateway", t, float(t))

    body = client.get("/api/v1/metrics", params={"since_ms": 1}).json()

    assert body["series"] == {"health.gateway": [[2, 2.0], [3, 3.0]]}
    assert isinstance(body["now_ms"], int)


def test_since_ms_defaults_to_everything_and_nulls_survive(world: ApiWorld, client: TestClient) -> None:
    world.metrics.append("health.gateway", 1, None)
    world.metrics.append("health.gateway", 2, 5.5)

    body = client.get("/api/v1/metrics").json()

    assert body["series"]["health.gateway"] == [[1, None], [2, 5.5]]


def test_prefix_filters_and_repeats(world: ApiWorld, client: TestClient) -> None:
    world.metrics.append("health.gateway", 1, 1.0)
    world.metrics.append("local.down_bps", 1, 2.0)
    world.metrics.append("traffic.down.10.0.0.2", 1, 3.0)

    one = client.get("/api/v1/metrics", params={"prefix": "health."}).json()
    two = client.get("/api/v1/metrics", params=[("prefix", "health."), ("prefix", "local.")]).json()
    none = client.get("/api/v1/metrics", params={"prefix": "nope."}).json()

    assert list(one["series"]) == ["health.gateway"]
    assert list(two["series"]) == ["health.gateway", "local.down_bps"]
    assert none["series"] == {}


def test_long_series_hold_720_samples_and_others_120(world: ApiWorld, client: TestClient) -> None:
    for t in range(1, 801):
        world.metrics.append("health.gateway", t, 1.0)
        world.metrics.append("health.device.x", t, 1.0)

    series = client.get("/api/v1/metrics").json()["series"]

    assert len(series["health.gateway"]) == 720
    assert len(series["health.device.x"]) == 120


def test_a_non_integer_since_ms_is_422(client: TestClient) -> None:
    assert client.get("/api/v1/metrics", params={"since_ms": "abc"}).status_code == 422
