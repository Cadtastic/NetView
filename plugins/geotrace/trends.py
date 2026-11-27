"""Bucket saved traces into the series the charts draw. Pure: no clock, no I/O."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from .changes import parse_signature
from .model import Trace

BUCKETS = 96


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def bucket(
    traces: Sequence[Trace], since_ms: int, until_ms: int, buckets: int = BUCKETS
) -> dict[str, list[Any]]:
    """Median round-trip time, hop count and loss per bucket, and when the route changed.

    ``traces`` must be oldest first. The range is cut into ``buckets`` equal slices; each point is
    ``[bucket start in ms, median or None]`` and a slice with no data is ``None``. A change is a done,
    reached trace whose route (its signature) differs from the previous such trace's; a trace with an
    empty signature (every hop silent or private) is neither a change nor a baseline.
    """
    width = (until_ms - since_ms) / buckets
    rtt: list[list[float]] = [[] for _ in range(buckets)]
    hops: list[list[float]] = [[] for _ in range(buckets)]
    loss: list[list[float]] = [[] for _ in range(buckets)]
    changes: list[int] = []
    previous: list[Any] | None = None
    for t in traces:
        if not since_ms <= t.started_ms <= until_ms:
            continue
        i = min(int((t.started_ms - since_ms) / width), buckets - 1) if width > 0 else 0
        if t.rtt_ms is not None:
            rtt[i].append(t.rtt_ms)
        if t.status == "done":
            hops[i].append(float(t.hop_count))
        if t.loss_pct is not None:
            loss[i].append(t.loss_pct)
        if t.status == "done" and t.reached:
            route = parse_signature(t.signature)
            if route:
                if previous is not None and route != previous:
                    changes.append(t.started_ms)
                previous = route

    def series(groups: list[list[float]]) -> list[list[Any]]:
        return [[since_ms + int(i * width), _median(g)] for i, g in enumerate(groups)]

    return {"rtt": series(rtt), "hops": series(hops), "loss": series(loss), "changes": changes}
