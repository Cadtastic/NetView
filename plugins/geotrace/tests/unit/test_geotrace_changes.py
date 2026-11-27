from __future__ import annotations

from netview_local_plugins.geotrace.changes import (
    ChangeTracker,
    first_difference,
    parse_signature,
    signature,
    signature_json,
)
from netview_local_plugins.geotrace.model import Hop, Target, Trace

MIN = 60_000
HOUR = 60 * MIN
P = "GeoTrace · "

TARGET = Target(1, "netflix.com", "netflix.com", "ipv4", 15, True, 0, 0)


def hop(n: int, asn: int | None, city: str, placement: str = "located") -> Hop:
    return Hop(n, f"10.0.0.{n}", (5.0,), city, "", "US", 1.0, 2.0, asn, "", placement, True)


def route(*cities: str) -> tuple[Hop, ...]:
    return tuple(hop(i + 1, 100 + i, c) for i, c in enumerate(cities))


A = route("Seattle", "Salt Lake City", "Chicago")
B = route("Seattle", "Dallas", "Chicago")


def trace(
    at: int,
    hops: tuple[Hop, ...] = A,
    rtt: float | None = 40.0,
    status: str = "done",
    reached: bool = True,
) -> Trace:
    return Trace(
        id=at,
        target_id=1,
        trigger="scheduled",
        mode="trace",
        status=status,
        error=None,
        started_ms=at - 1000,
        finished_ms=at,
        resolved_ip="1.1.1.1",
        family="ipv4",
        reached=reached,
        hop_count=len(hops),
        rtt_ms=rtt,
        loss_pct=0.0,
        jitter_ms=1.0,
        ping_min_ms=None,
        ping_max_ms=None,
        signature="[]",
        hops=hops,
    )


def fail(at: int) -> Trace:
    return trace(at, (), None, status="failed", reached=False)


def feed(tracker: ChangeTracker, traces: list[Trace]) -> list[list[str]]:
    return [tracker.observe(TARGET, t, []) for t in traces]


def test_signature_collapses_and_uses_located_only() -> None:
    hops = (
        hop(1, None, "", "home"),
        hop(2, 100, "Seattle"),
        hop(3, 100, "Seattle"),
        hop(4, None, "", "assumed"),
        hop(5, 200, "Dallas"),
        hop(6, None, "", "none"),
    )
    assert signature(hops) == [(100, "Seattle"), (200, "Dallas")]
    assert signature(()) == []


def test_signature_json_round_trip_and_bad_input() -> None:
    hops = (hop(1, 100, "Seattle"), hop(2, None, "Dallas"))
    assert signature_json(hops) == '[[100, "Seattle"], [null, "Dallas"]]'
    assert parse_signature(signature_json(hops)) == [(100, "Seattle"), (None, "Dallas")]
    assert parse_signature("not json") == []
    assert parse_signature('{"a": 1}') == []


def test_first_difference() -> None:
    a = [(1, "x"), (2, "y")]
    assert first_difference(a, list(a)) is None
    assert first_difference(a, [(1, "x"), (3, "y")]) == 1
    assert first_difference(a, [(1, "x")]) == 1
    assert first_difference([], a) == 0


def test_identical_signatures_no_events() -> None:
    t = ChangeTracker()
    assert feed(t, [trace(i * 15 * MIN) for i in range(1, 5)]) == [[], [], [], []]


def test_single_different_trace_then_back_is_a_flap() -> None:
    t = ChangeTracker()
    out = feed(t, [trace(1 * MIN), trace(2 * MIN, B), trace(3 * MIN, A), trace(4 * MIN, A)])
    assert out == [[], [], [], []]


def test_two_in_a_row_fires_once_with_exact_text() -> None:
    t = ChangeTracker()
    out = feed(
        t,
        [trace(1, A, 40.0), trace(2, B, 50.0), trace(3, B, 54.0), trace(4, B, 54.0)],
    )
    assert out[:2] == [[], []]
    assert out[2] == [f"{P}netflix.com: route changed at hop 2 (Salt Lake City → Dallas), +14 ms"]
    assert out[3] == []


def test_negative_delta_and_missing_rtt() -> None:
    t = ChangeTracker()
    out = feed(t, [trace(1, A, 40.0), trace(2, B, 37.0), trace(3, B, 37.0)])
    assert out[2] == [f"{P}netflix.com: route changed at hop 2 (Salt Lake City → Dallas), -3 ms"]
    t = ChangeTracker()
    out = feed(t, [trace(1, A, None), trace(2, B, 37.0), trace(3, B, 37.0)])
    assert out[2] == [f"{P}netflix.com: route changed at hop 2 (Salt Lake City → Dallas)"]


def test_empty_signature_never_fires() -> None:
    silent = (hop(1, None, "", "home"), hop(2, None, "", "none"))
    t = ChangeTracker()
    out = feed(t, [trace(1, A), trace(2, silent), trace(3, silent), trace(4, A), trace(5, A)])
    assert out == [[], [], [], [], []]
    t = ChangeTracker()
    assert feed(t, [trace(1, silent), trace(2, silent), trace(3, A), trace(4, A)]) == [[]] * 4


def test_slowdown_fires_once_then_quiet_for_six_hours() -> None:
    t = ChangeTracker()
    now = 30 * HOUR
    old = [(now - 20 * HOUR + i * HOUR, 41.0) for i in range(10)]
    recent = [(now - 40 * MIN, 58.0), (now - 20 * MIN, 58.0)]
    text = f"{P}netflix.com: slower, 58 ms (usually 41 ms)"
    assert t.observe(TARGET, trace(now, rtt=58.0), old + recent) == [text]
    assert t.observe(TARGET, trace(now + 15 * MIN, rtt=58.0), old + recent) == []
    later = now + 6 * HOUR + MIN
    history = [(later - 2 * HOUR, 41.0)] * 5 + [(later - 10 * MIN, 58.0)]
    assert t.observe(TARGET, trace(later, rtt=58.0), history) == [text]


def test_nine_ms_worse_is_not_a_slowdown_and_needs_ratio() -> None:
    now = 30 * HOUR
    base = [(now - 5 * HOUR, 10.0)]
    assert ChangeTracker().observe(TARGET, trace(now, rtt=19.0), base) == []
    assert len(ChangeTracker().observe(TARGET, trace(now, rtt=20.0), base)) == 1
    assert ChangeTracker().observe(TARGET, trace(now, rtt=130.0), [(now - 5 * HOUR, 100.0)]) == []
    assert ChangeTracker().observe(TARGET, trace(now, rtt=500.0), []) == []


def test_unreachable_after_three_failures_then_back() -> None:
    t = ChangeTracker()
    out = feed(t, [trace(1), fail(2), fail(3), fail(4), fail(5), trace(6)])
    assert out[:3] == [[], [], []]
    assert out[3] == [f"{P}netflix.com: unreachable (3 traces in a row)"]
    assert out[4] == []
    assert out[5] == [f"{P}netflix.com: reachable again"]


def test_two_failures_then_success_is_silent() -> None:
    t = ChangeTracker()
    assert feed(t, [fail(1), fail(2), trace(3), trace(4)]) == [[]] * 4


def test_done_but_not_reached_counts_as_failure_and_skips_route_logic() -> None:
    t = ChangeTracker()

    def partial(at: int) -> Trace:
        return trace(at, B[:2], None, reached=False)

    out = feed(t, [trace(1), partial(2), partial(3), partial(4)])
    assert out[:3] == [[], [], []]
    assert out[3] == [f"{P}netflix.com: unreachable (3 traces in a row)"]


def test_failure_does_not_count_toward_route_change() -> None:
    t = ChangeTracker()
    assert feed(t, [trace(1, A), fail(2), trace(3, A), trace(4, A)]) == [[]] * 4


def test_seed_rebuilds_state_silently() -> None:
    t = ChangeTracker()
    t.seed(TARGET.id, [trace(3, B), trace(2, B), trace(1, A)])  # newest first
    assert t.observe(TARGET, trace(4, B), []) == []
    t2 = ChangeTracker()
    t2.seed(TARGET.id, [trace(2, B), trace(1, A)])
    out = t2.observe(TARGET, trace(3, B), [])
    assert out == [f"{P}netflix.com: route changed at hop 2 (Salt Lake City → Dallas), +0 ms"]


def test_targets_are_tracked_separately() -> None:
    other = Target(2, "work VPN", "10.1.1.1", "ipv4", 15, True, 0, 0)
    t = ChangeTracker()
    t.observe(TARGET, trace(1, A), [])
    t.observe(TARGET, trace(2, B), [])
    assert t.observe(other, trace(3, B), []) == []
