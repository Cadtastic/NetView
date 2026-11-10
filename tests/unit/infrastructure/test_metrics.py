from netview.infrastructure.metrics import RingMetricsStore


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
