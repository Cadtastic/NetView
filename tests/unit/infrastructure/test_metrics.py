from netview.infrastructure.metrics import RingMetricsStore
from netview.sdk.testing.fakes import InMemoryMetrics


def test_metrics_ring_keeps_last_120() -> None:
    m = RingMetricsStore()
    for i in range(150):
        m.append("rtt", i, float(i))
    s = m.series("rtt")
    assert len(s) == 120
    assert s[0] == (30, 30.0)
    assert s[-1] == (149, 149.0)


def test_series_limit_none_values_and_names() -> None:
    m = RingMetricsStore()
    m.append("a.x", 1, None)
    m.append("a.x", 2, 2.0)
    m.append("b.y", 1, 1.0)
    assert m.series("a.x", limit=1) == [(2, 2.0)]
    assert m.series("a.x")[0] == (1, None)
    assert m.series("missing") == []
    assert m.names("a.") == ["a.x"]
    assert m.names() == ["a.x", "b.y"]


def test_long_prefixes_keep_720_and_the_rest_120() -> None:
    m = RingMetricsStore(long_prefixes=("health.gateway", "health.dns.", "local."), long_maxlen=720)
    for i in range(800):
        m.append("health.gateway", i, 1.0)
        m.append("health.dns.1.1.1.1", i, 1.0)
        m.append("local.down_bps", i, 1.0)
        m.append("health.device.x", i, 1.0)
        m.append("traffic.down.1.2.3.4", i, 1.0)
    assert len(m.series("health.gateway", 1000)) == 720
    assert len(m.series("health.dns.1.1.1.1", 1000)) == 720
    assert len(m.series("local.down_bps", 1000)) == 720
    assert len(m.series("health.device.x", 1000)) == 120
    assert len(m.series("traffic.down.1.2.3.4", 1000)) == 120


def test_snapshot_filters_by_prefix_and_time() -> None:
    m = RingMetricsStore()
    for t in (1, 2, 3):
        m.append("health.gateway", t, float(t))
        m.append("local.down_bps", t, None)
    assert m.snapshot() == {
        "health.gateway": [(1, 1.0), (2, 2.0), (3, 3.0)],
        "local.down_bps": [(1, None), (2, None), (3, None)],
    }
    assert m.snapshot(since_ms=1) == {
        "health.gateway": [(2, 2.0), (3, 3.0)],
        "local.down_bps": [(2, None), (3, None)],
    }
    assert m.snapshot(("health.",), 2) == {"health.gateway": [(3, 3.0)]}
    assert m.snapshot(("nope.",)) == {}
    assert m.snapshot(since_ms=3) == {}


def test_snapshot_returns_the_whole_buffer_not_the_default_limit() -> None:
    m = RingMetricsStore(long_prefixes=("local.",), long_maxlen=720)
    for i in range(1, 701):
        m.append("local.down_bps", i, 1.0)
    assert len(m.snapshot(("local.",))["local.down_bps"]) == 700


def test_drop_removes_a_series_and_is_idempotent() -> None:
    m = RingMetricsStore()
    m.append("a", 1, 1.0)
    m.drop("a")
    m.drop("a")
    assert m.names() == [] and m.series("a") == []


def test_the_in_memory_fake_matches_the_ring_store() -> None:
    fake = InMemoryMetrics()
    for t in (1, 2, 3):
        fake.append("health.gateway", t, float(t))
        fake.append("other", t, None)
    assert fake.snapshot(("health.",), 1) == {"health.gateway": [(2, 2.0), (3, 3.0)]}
    assert set(fake.snapshot()) == {"health.gateway", "other"}
    fake.drop("other")
    fake.drop("other")
    assert fake.names() == ["health.gateway"]
