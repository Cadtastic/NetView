"""Route signatures and the change events GeoTrace raises from them.

Pure: no clock, no I/O. The runner feeds finished traces to a ``ChangeTracker``
and posts the returned texts as NetView events.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from .model import Hop, Target, Trace

PREFIX = "GeoTrace · "
HOUR_MS = 3_600_000
SLOWDOWN_RATIO = 1.4
SLOWDOWN_MIN_EXTRA_MS = 10.0
SLOWDOWN_QUIET_MS = 6 * HOUR_MS
UNREACHABLE_AFTER = 3

Signature = list[tuple[int | None, str]]


def _entries(hops: Sequence[Hop]) -> list[tuple[tuple[int | None, str], int]]:
    """Located hops as ((asn, city), first hop number), consecutive duplicates collapsed."""
    out: list[tuple[tuple[int | None, str], int]] = []
    for h in hops:
        if h.placement != "located":
            continue
        key = (h.asn, h.city)
        if out and out[-1][0] == key:
            continue
        out.append((key, h.n))
    return out


def signature(hops: Sequence[Hop]) -> Signature:
    return [key for key, _ in _entries(hops)]


def signature_json(hops: Sequence[Hop]) -> str:
    return json.dumps([[asn, city] for asn, city in signature(hops)])


def parse_signature(text: str) -> Signature:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out: Signature = []
    for item in data:
        if not (isinstance(item, list) and len(item) == 2):
            return []
        asn, city = item
        out.append((asn if isinstance(asn, int) else None, str(city)))
    return out


def first_difference(a: Sequence[tuple[int | None, str]], b: Sequence[tuple[int | None, str]]) -> int | None:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


@dataclass
class _State:
    baseline: Signature | None = None
    baseline_ns: list[int] = field(default_factory=list)
    baseline_rtt: float | None = None
    pending: Signature | None = None
    failures: int = 0
    unreachable: bool = False
    last_slow_ms: int | None = None
    rebaseline: bool = False  # take the next good signature as the baseline, with no event


class ChangeTracker:
    """Per-target change detection, held in memory.

    A done trace that did not reach the target counts as a failure and is left
    out of the route and slowdown logic: a partial route would look like a change.
    """

    def __init__(self) -> None:
        self._states: dict[int, _State] = {}

    def forget(self, target_id: int) -> None:
        """Drop everything remembered about a target that was deleted."""
        self._states.pop(target_id, None)

    def rebaseline_all(self) -> None:
        """Accept each target's next good signature as its new baseline, without an event.

        Called after the location database was replaced: a hop DB-IP moved to another city then reads as
        a changed route when nothing about the route changed."""
        for state in list(self._states.values()):
            state.rebaseline = True

    def seed(self, target_id: int, traces: Sequence[Trace]) -> None:
        """Rebuild state from saved traces, newest first, without raising events.

        The runner must pass traces of every status (``latest(id, 10, status=None)``):
        trailing failures (failed, or done but not reached) restore the unreachable state.
        The route baseline is the newest signature seen in two consecutive done-and-reached
        traces, else the newest such trace's signature; a newer differing signature is pending.
        """
        state = self._states[target_id] = _State()
        for t in traces:
            if t.status != "failed" and t.reached:
                break
            state.failures += 1
        state.unreachable = state.failures >= UNREACHABLE_AFTER
        good = []
        for t in traces:
            if t.status == "failed" or not t.reached:
                continue
            entries = _entries(t.hops)
            if entries:
                good.append((t, [k for k, _ in entries], [n for _, n in entries]))
        if not good:
            return
        pick = next((i for i in range(len(good) - 1) if good[i][1] == good[i + 1][1]), 0)
        t, sig, ns = good[pick]
        state.baseline, state.baseline_ns, state.baseline_rtt = sig, ns, t.rtt_ms
        newest = good[0][1]
        state.pending = newest if newest != sig else None

    def observe(self, target: Target, trace: Trace, recent_rtts: Sequence[tuple[int, float]]) -> list[str]:
        """Take one finished trace; return event texts.

        ``recent_rtts`` are (time_ms, rtt_ms) of earlier finished traces only, excluding the
        current one, which is always appended here.
        """
        state = self._states.setdefault(target.id, _State())
        now = trace.finished_ms or trace.started_ms
        events: list[str] = []
        label = f"{PREFIX}{target.name}: "

        if trace.status == "failed" or not trace.reached:
            state.failures += 1
            if state.failures == UNREACHABLE_AFTER:
                state.unreachable = True
                events.append(f"{label}unreachable ({UNREACHABLE_AFTER} traces in a row)")
            return events

        state.failures = 0
        if state.unreachable:
            state.unreachable = False
            events.append(f"{label}reachable again")

        change = self._route(state, trace)
        if change is not None:
            events.append(f"{label}route changed at hop {change}")

        slow = self._slowdown(state, now, trace.rtt_ms, recent_rtts)
        if slow is not None:
            events.append(f"{label}{slow}")
        return events

    @staticmethod
    def _route(state: _State, trace: Trace) -> str | None:
        """Update route state; on a confirmed change return the text after 'at hop '."""
        if trace.status == "failed" or not trace.reached:
            return None
        entries = _entries(trace.hops)
        sig = [key for key, _ in entries]
        ns = [n for _, n in entries]
        if not sig:
            return None
        if state.rebaseline:
            state.rebaseline = False
            state.baseline, state.baseline_ns = sig, ns
            state.baseline_rtt = trace.rtt_ms
            state.pending = None
            return None
        if state.baseline is None or sig == state.baseline:
            state.baseline, state.baseline_ns = sig, ns
            state.baseline_rtt = trace.rtt_ms
            state.pending = None
            return None
        if state.pending != sig:
            state.pending = sig
            return None
        idx = first_difference(state.baseline, sig)
        assert idx is not None
        old = state.baseline[idx][1] if idx < len(state.baseline) else "end of route"
        new = sig[idx][1] if idx < len(sig) else "end of route"
        if idx < len(ns):
            hop_n = ns[idx]
        elif idx < len(state.baseline_ns):
            hop_n = state.baseline_ns[idx]
        else:
            hop_n = ns[-1]
        text = f"{hop_n} ({old} → {new})"
        if trace.rtt_ms is not None and state.baseline_rtt is not None:
            text += f", {round(trace.rtt_ms - state.baseline_rtt):+d} ms"
        state.baseline, state.baseline_ns = sig, ns
        state.baseline_rtt = trace.rtt_ms
        state.pending = None
        return text

    @staticmethod
    def _slowdown(
        state: _State, now: int, rtt: float | None, recent_rtts: Sequence[tuple[int, float]]
    ) -> str | None:
        samples = list(recent_rtts)
        if rtt is not None:
            samples.append((now, rtt))
        hour = [v for t, v in samples if now - HOUR_MS < t <= now]
        before = [v for t, v in samples if now - 25 * HOUR_MS < t <= now - HOUR_MS]
        if not hour or not before:
            return None
        current = statistics.median(hour)
        usual = statistics.median(before)
        if current <= usual * SLOWDOWN_RATIO or current - usual < SLOWDOWN_MIN_EXTRA_MS:
            return None
        if state.last_slow_ms is not None and now - state.last_slow_ms < SLOWDOWN_QUIET_MS:
            return None
        state.last_slow_ms = now
        return f"slower, {round(current)} ms (usually {round(usual)} ms)"
