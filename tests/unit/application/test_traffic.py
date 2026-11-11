from collections.abc import Iterable
from typing import Any

from netview.application.usecases.traffic import PollTraffic, TrafficLedger
from netview.domain.samples import TrafficReading
from netview.sdk.testing.fakes import FakeClock, InMemoryMetrics

IP = "192.168.1.20"


def reading(ip: str = IP, t: int = 0, down: int = 0, up: int = 0, **extra: Any) -> TrafficReading:
    return TrafficReading(ip, t, down, up, extra)


def listed(ip: str = IP, t: int = 0) -> TrafficReading:
    """A client the source lists but gave no byte counters for."""
    return TrafficReading(ip, t, None, None, {})


def make() -> tuple[TrafficLedger, InMemoryMetrics]:
    metrics = InMemoryMetrics()
    return TrafficLedger(metrics), metrics


def test_rate_from_two_readings() -> None:
    ledger, metrics = make()
    ledger.record("starlink", [reading(t=0, down=0, up=0)])
    ledger.record("starlink", [reading(t=5000, down=5_000_000, up=1_000_000)])
    (view,) = ledger.views()
    assert view.down_bps == 8_000_000.0 and view.up_bps == 1_600_000.0
    assert view.down_total == 5_000_000 and view.up_total == 1_000_000
    assert metrics.series(f"traffic.down.{IP}") == [(0, None), (5000, 8_000_000.0)]
    assert metrics.series(f"traffic.up.{IP}") == [(0, None), (5000, 1_600_000.0)]


def test_first_reading_has_no_rate() -> None:
    ledger, _ = make()
    ledger.record("s", [reading(t=0, down=100)])
    (view,) = ledger.views()
    assert view.down_bps is None and view.up_bps is None
    assert view.down_avg_bps is None and view.up_avg_bps is None


def test_counters_going_backwards_append_a_null_and_recover() -> None:
    ledger, metrics = make()
    ledger.record("s", [reading(t=0, down=10_000_000)])
    ledger.record("s", [reading(t=5000, down=15_000_000)])
    ledger.record("s", [reading(t=10_000, down=1_000)])  # the router rebooted
    assert metrics.series(f"traffic.down.{IP}")[-1] == (10_000, None)
    (view,) = ledger.views()
    assert view.down_bps is None
    ledger.record("s", [reading(t=15_000, down=2_501_000)])  # recovers from the new baseline
    assert ledger.views()[0].down_bps == 4_000_000.0


def test_averages_are_the_mean_of_non_null_samples() -> None:
    ledger, _ = make()
    ledger.record("s", [reading(t=0, down=0)])
    ledger.record("s", [reading(t=1000, down=1000)])  # 8000 bps
    ledger.record("s", [reading(t=2000, down=4000)])  # 24000 bps
    ledger.record("s", [reading(t=3000, down=0)])  # reset: null
    view = ledger.views()[0]
    assert view.down_avg_bps == 16000.0
    assert view.down_bps is None


def test_extra_and_source_are_kept() -> None:
    ledger, _ = make()
    ledger.record("starlink", [reading(name="Laptop", role="wifi", future_key=1)])
    view = ledger.views()[0]
    assert view.source == "starlink" and view.seen_ms == 0
    assert dict(view.extra) == {"name": "Laptop", "role": "wifi", "future_key": 1}


def test_ip_unseen_for_more_than_600_s_is_dropped_with_its_series() -> None:
    ledger, metrics = make()
    ledger.record("s", [reading("192.168.1.20", 0), reading("192.168.1.21", 0)])
    ledger.record("s", [reading("192.168.1.21", 600_000)])  # exactly 600 s: kept
    assert {v.ip for v in ledger.views()} == {"192.168.1.20", "192.168.1.21"}
    ledger.record("s", [reading("192.168.1.21", 601_000)])
    assert [v.ip for v in ledger.views()] == ["192.168.1.21"]
    assert metrics.names("traffic.") == ["traffic.down.192.168.1.21", "traffic.up.192.168.1.21"]


def test_totals_sum_the_latest_rates_per_source() -> None:
    ledger, _ = make()
    ledger.record("a", [reading("192.168.1.20", 0), reading("192.168.1.21", 0)])
    ledger.record("a", [reading("192.168.1.20", 1000, 1000, 500), reading("192.168.1.21", 1000, 2000, 0)])
    ledger.record("b", [reading("192.168.1.30", 0)])
    totals = {t.source: t for t in ledger.totals()}
    a = totals["a"]
    assert (a.clients, a.down_bps, a.up_bps, a.t_ms) == (2, 24000.0, 4000.0, 1000)
    assert (totals["b"].clients, totals["b"].down_bps) == (1, 0.0)


def test_views_are_in_numeric_ip_order() -> None:
    ledger, _ = make()
    ledger.record("s", [reading("192.168.1.100"), reading("192.168.1.9"), reading("192.168.1.20")])
    assert [v.ip for v in ledger.views()] == ["192.168.1.9", "192.168.1.20", "192.168.1.100"]


class _Provider:
    def read(self) -> Iterable[TrafficReading]:
        yield reading(t=1)


def test_poll_traffic_records_under_the_source() -> None:
    ledger, _ = make()
    PollTraffic(ledger)("starlink", _Provider())
    assert [(v.ip, v.source) for v in ledger.views()] == [(IP, "starlink")]


def test_views_and_totals_expire_at_read_time_when_nothing_new_arrives() -> None:
    clock = FakeClock()
    metrics = InMemoryMetrics()
    ledger = TrafficLedger(metrics, clock)
    t0 = clock.now_ms()
    ledger.record("s", [reading(t=t0, down=0), reading("192.168.1.21", t=t0, down=0)])
    clock.advance(600_000)  # exactly 600 s: still there
    assert len(ledger.views()) == 2 and [t.source for t in ledger.totals()] == ["s"]
    clock.advance(1_000)
    assert ledger.views() == []
    assert ledger.totals() == []
    assert metrics.names("traffic.") == []  # the series went with the clients


def test_a_stale_source_is_dropped_while_a_fresh_one_stays() -> None:
    clock = FakeClock()
    ledger = TrafficLedger(InMemoryMetrics(), clock)
    ledger.record("old", [reading("192.168.1.20", t=clock.now_ms())])
    clock.advance(601_000)
    ledger.record("new", [reading("192.168.1.30", t=clock.now_ms())])
    assert [t.source for t in ledger.totals()] == ["new"]
    assert [v.ip for v in ledger.views()] == ["192.168.1.30"]


def test_a_client_listed_without_counters_is_counted_and_has_no_rate_or_total() -> None:
    ledger, metrics = make()
    ledger.record("s", [reading(t=0, down=100, up=50), listed("192.168.1.21")])
    by_ip = {v.ip: v for v in ledger.views()}
    assert set(by_ip) == {IP, "192.168.1.21"}
    bare = by_ip["192.168.1.21"]
    assert (bare.down_bps, bare.up_bps, bare.down_total, bare.up_total) == (None, None, None, None)
    assert metrics.series("traffic.down.192.168.1.21") == [(0, None)]
    assert ledger.totals()[0].clients == 2


def test_a_reading_without_counters_keeps_the_last_known_counters_for_the_next_rate() -> None:
    ledger, _ = make()
    ledger.record("s", [reading(t=0, down=0, up=0)])
    ledger.record("s", [listed(t=5000)])
    assert ledger.views()[0].down_total == 0  # the earlier counters are still the reference
    ledger.record("s", [reading(t=10_000, down=10_000_000, up=0)])
    assert ledger.views()[0].down_bps == 8_000_000.0
