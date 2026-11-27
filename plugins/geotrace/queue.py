"""When targets come due, and the queue the single worker takes its jobs from."""

from __future__ import annotations

import dataclasses
import hashlib
import secrets
import threading
from collections import deque
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass

from .model import Target
from .runner import Job, LiveTrace

MINUTE_MS = 60_000
LIVE_KEPT_MS = 10 * MINUTE_MS  # a finished trace stays readable by its provisional id this long
MAPPING_KEPT_MS = 24 * 60 * MINUTE_MS  # and its provisional id keeps pointing at the saved trace this long


def _offset_ms(target_id: int, interval_ms: int) -> int:
    return int(hashlib.sha256(str(target_id).encode()).hexdigest(), 16) % interval_ms


VALID_INTERVALS = (5, 15, 30, 60)


def due_targets(
    targets: Sequence[Target],
    last_started: Mapping[int, int],
    now_ms: int,
    on_invalid: Callable[[Target], None] | None = None,
) -> list[int]:
    """Ids of the enabled targets whose next run is due.

    A target never traced is due at ``created_ms`` plus a hash of its id (modulo its interval), so a batch of
    new targets spreads over the interval. After that it is due one interval after its last start, however
    long ago that was: an overdue target is listed once, not once per missed interval. A target whose
    interval is not one of 5, 15, 30, 60 is skipped and passed to ``on_invalid``.
    """
    due: list[int] = []
    for t in targets:
        if not t.enabled:
            continue
        if t.interval_min not in VALID_INTERVALS:
            if on_invalid is not None:
                on_invalid(t)
            continue
        interval_ms = t.interval_min * MINUTE_MS
        last = last_started.get(t.id)
        at = t.created_ms + _offset_ms(t.id, interval_ms) if last is None else last + interval_ms
        if now_ms >= at:
            due.append(t.id)
    return due


@dataclass
class _Finished:
    live: LiveTrace | None  # released once the live window has passed
    saved_id: int


def _key(job: Job) -> Hashable:
    if job.target_id is not None:
        return job.target_id
    return ("once", job.address.strip().lower(), job.family, job.mode)


class TraceQueue:
    """Jobs waiting for the worker, with one job per target (or per one-off address) queued or running.

    Every job gets a provisional trace id (negative, so it can never be a saved id, and counting down from a random
    start so ids of an earlier process do not match) when it is put. When the
    worker finishes it, ``finish`` records the saved id, so a later lookup by the provisional id finds the
    saved trace; a trace that could not be saved stays readable as a live trace for ten minutes.
    """

    def __init__(self, now_ms: Callable[[], int]) -> None:
        self._now = now_ms
        self._cond = threading.Condition()
        self._pending: deque[tuple[int, Job]] = deque()
        self._active: dict[int, tuple[Job, LiveTrace]] = {}  # queued or running
        self._by_key: dict[Hashable, int] = {}
        self._finished: dict[int, _Finished] = {}
        self._live_expiry: deque[tuple[int, int]] = deque()  # (until_ms, id), oldest first
        self._map_expiry: deque[tuple[int, int]] = deque()
        # A random start per process: a browser that still holds an id from before a restart must not match a new job.
        self._next_id = -1 - secrets.randbelow(1_000_000_000)
        self._closed = False

    def put(self, job: Job, front: bool = False) -> int | None:
        """Queue a job; None when one for the same target is already queued or running (or after close)."""
        with self._cond:
            if self._closed:
                return None
            if _key(job) in self._by_key:
                if front:
                    self._promote(_key(job), job)
                return None
            trace_id = self._next_id
            self._next_id -= 1
            self._active[trace_id] = (
                job,
                LiveTrace(
                    id=trace_id,
                    started_ms=self._now(),
                    target_id=job.target_id,
                    mode=job.mode,
                    trigger=job.trigger,
                ),
            )
            self._by_key[_key(job)] = trace_id
            entry = (trace_id, job)
            if front:
                self._pending.appendleft(entry)
            else:
                self._pending.append(entry)
            self._cond.notify()
            return trace_id

    def _promote(self, key: Hashable, job: Job) -> None:
        """A wanted-now request for a job still waiting: move it to the front with the new trigger."""
        trace_id = self._by_key[key]
        for i, (queued_id, _) in enumerate(self._pending):
            if queued_id == trace_id:
                del self._pending[i]
                promoted = dataclasses.replace(self._active[trace_id][0], trigger=job.trigger)
                self._active[trace_id] = (promoted, self._active[trace_id][1])
                self._pending.appendleft((trace_id, promoted))
                return

    def drop(self, target_id: int) -> bool:
        """Remove the job still waiting for this target (its live trace fails). False if none waits."""
        with self._cond:
            trace_id = self._by_key.get(target_id)
            for i, (queued_id, _) in enumerate(self._pending):
                if queued_id == trace_id and trace_id is not None:
                    del self._pending[i]
                    self._active[trace_id][1].update(status="failed", error="the target was removed")
                    self._finish_unlocked(trace_id, 0)
                    return True
            return False

    def fail(self, trace_id: int, message: str) -> None:
        """End a job the worker took but will not run."""
        with self._cond:
            if trace_id in self._active:
                self._active[trace_id][1].update(status="failed", error=message)
                self._finish_unlocked(trace_id, 0)

    def get(self, timeout_s: float) -> tuple[int, Job] | None:
        """The next job (now counted as running), waiting up to ``timeout_s``; None on timeout or close."""
        with self._cond:
            self._cond.wait_for(lambda: bool(self._pending) or self._closed, timeout_s)
            if self._closed or not self._pending:
                return None
            return self._pending.popleft()

    def finish(self, trace_id: int, saved_id: int) -> None:
        """The worker is done with a job. ``saved_id`` is 0 when the trace was not stored."""
        with self._cond:
            if trace_id in self._active:
                self._finish_unlocked(trace_id, saved_id)

    def live(self, trace_id: int) -> LiveTrace | None:
        with self._cond:
            if trace_id in self._active:
                return self._active[trace_id][1]
            now = self._now()
            self._prune(now)
            found = self._finished.get(trace_id)
            return found.live if found is not None else None

    def resolve_id(self, trace_id: int) -> int | None:
        """The saved trace id for a trace id as the API hands it out; None if it is not (yet) saved."""
        if trace_id > 0:
            return trace_id
        with self._cond:
            self._prune(self._now())
            found = self._finished.get(trace_id)
            return found.saved_id if found is not None and found.saved_id > 0 else None

    def running_for(self, target_id: int) -> int | None:
        """The provisional id of the job queued or running for this target, if any."""
        with self._cond:
            return self._by_key.get(target_id)

    def existing_id(self, job: Job) -> int | None:
        """The provisional id of the queued or running job that ``job`` would duplicate."""
        with self._cond:
            return self._by_key.get(_key(job))

    def close(self) -> None:
        """Stop handing out jobs; the ones still waiting are marked failed."""
        with self._cond:
            self._closed = True
            for trace_id, _ in self._pending:
                self._active[trace_id][1].update(status="failed", error="NetView is shutting down")
                self._finish_unlocked(trace_id, 0)
            self._pending.clear()
            self._cond.notify_all()

    def _finish_unlocked(self, trace_id: int, saved_id: int) -> None:
        job, live = self._active.pop(trace_id)
        self._by_key.pop(_key(job), None)
        now = self._now()
        self._finished[trace_id] = _Finished(live, saved_id)
        self._live_expiry.append((now + LIVE_KEPT_MS, trace_id))
        self._map_expiry.append((now + MAPPING_KEPT_MS, trace_id))
        self._prune(now)

    def _prune(self, now: int) -> None:
        """Release what has expired; only the expired entries are looked at."""
        while self._live_expiry and self._live_expiry[0][0] <= now:
            _, trace_id = self._live_expiry.popleft()
            found = self._finished.get(trace_id)
            if found is not None:
                found.live = None  # the hop list can go; the id mapping stays
                if found.saved_id <= 0:
                    del self._finished[trace_id]
        while self._map_expiry and self._map_expiry[0][0] <= now:
            self._finished.pop(self._map_expiry.popleft()[1], None)
