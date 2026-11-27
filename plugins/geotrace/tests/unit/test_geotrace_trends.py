"""Bucketing of saved traces for the charts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from netview_local_plugins.geotrace.model import Trace
from netview_local_plugins.geotrace.trends import bucket


def _trace(started_ms: int, **changes: Any) -> Trace:
    base = Trace(
        0, 1, "scheduled", "trace", "done", None, started_ms, started_ms + 5, "8.8.8.8", "ipv4", True, 4,
        10.0, 0.0, 0.0, 9.0, 11.0, '[[1, "A"]]', (),
    )  # fmt: skip
    return replace(base, **changes)


def test_median_per_bucket_with_gaps_as_null() -> None:
    traces = [
        _trace(10, rtt_ms=10.0),
        _trace(50, rtt_ms=30.0),
        _trace(60, rtt_ms=20.0),
        _trace(250, rtt_ms=5.0),
    ]
    out = bucket(traces, 0, 400, buckets=4)
    assert out["rtt"] == [[0, 20.0], [100, None], [200, 5.0], [300, None]]


def test_hops_and_loss_use_the_same_buckets() -> None:
    traces = [
        _trace(10, hop_count=4, loss_pct=0.0),
        _trace(20, hop_count=6, loss_pct=10.0),
        _trace(30, hop_count=5, loss_pct=20.0),
    ]
    out = bucket(traces, 0, 200, buckets=2)
    assert out["hops"] == [[0, 5.0], [100, None]]
    assert out["loss"] == [[0, 10.0], [100, None]]


def test_failed_traces_add_no_rtt_and_traces_outside_the_range_are_ignored() -> None:
    traces = [
        _trace(-5, rtt_ms=99.0),
        _trace(10, status="failed", error="x", rtt_ms=None, hop_count=0, loss_pct=None),
        _trace(20, rtt_ms=8.0),
        _trace(500, rtt_ms=99.0),
    ]
    out = bucket(traces, 0, 100, buckets=1)
    assert out["rtt"] == [[0, 8.0]]
    assert out["hops"] == [[0, 4.0]]


def test_the_last_instant_belongs_to_the_last_bucket() -> None:
    out = bucket([_trace(400, rtt_ms=7.0)], 0, 400, buckets=4)
    assert out["rtt"][3] == [300, 7.0]


def test_changes_are_where_the_signature_differs_from_the_previous_route() -> None:
    a, b = '[[1, "A"]]', '[[1, "B"]]'
    traces = [
        _trace(10, signature=a),
        _trace(20, signature=a),
        _trace(30, signature="[]"),  # silent route: neither a change nor a baseline
        _trace(40, signature=b),
        _trace(50, signature=b, status="failed", reached=False),
        _trace(60, signature=b),
        _trace(70, signature=a),
    ]
    assert bucket(traces, 0, 100, buckets=4)["changes"] == [40, 70]


def test_nothing_in_range_gives_all_null_buckets() -> None:
    out = bucket([], 0, 300, buckets=3)
    assert out == {
        "rtt": [[0, None], [100, None], [200, None]],
        "hops": [[0, None], [100, None], [200, None]],
        "loss": [[0, None], [100, None], [200, None]],
        "changes": [],
    }
