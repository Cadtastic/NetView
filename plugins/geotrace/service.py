"""GeoTrace's moving parts: stores, queue, the one worker thread, change tracker and DB-IP data (spec 6.3)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .changes import ChangeTracker
from .geo import HopLocator
from .geodata import GeoData
from .model import Target
from .placement import Home
from .queue import VALID_INTERVALS, TraceQueue, due_targets
from .runner import Job, LiveTrace, TraceRunner
from .settings import GeoTraceSettings
from .storage import TargetStore, TraceStore

MAX_TARGETS = 50
SEED_TRACES = 10
ONCE_KEEP_DAYS = 7
STOP_WAIT_S = 5.0
DAY_MS = 86_400_000


class TargetLimitError(Exception):
    def __init__(self) -> None:
        super().__init__(f"at most {MAX_TARGETS} targets")


def _check_interval(interval_min: int) -> None:
    if interval_min not in VALID_INTERVALS:
        raise ValueError("interval must be 5, 15, 30 or 60 minutes")


class GeoTraceService:
    def __init__(
        self,
        ctx: Any,
        settings: GeoTraceSettings,
        geo: GeoData | None = None,
        tracker: ChangeTracker | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._ctx = ctx
        self._stopping = threading.Event()
        self.settings = settings
        self.targets = TargetStore(ctx.unit_of_work)
        self.traces = TraceStore(ctx.unit_of_work)
        self.queue = TraceQueue(ctx.clock.now_ms)
        self.tracker = tracker if tracker is not None else ChangeTracker()
        self.geo = geo if geo is not None else GeoData(ctx.files_dir / "geo", ctx.clock)
        self._runner = TraceRunner(
            ctx,
            self.traces,
            self.tracker,
            self.home,
            self._locator,
            sleep=sleep,
            should_stop=self._stopping.is_set,
        )
        self._last_started: dict[int, int] = {}  # target id -> when its newest run was queued
        self._lock = threading.Lock()
        self._warned: set[int] = set()  # targets already logged for an invalid interval
        self._worker: threading.Thread | None = None
        self._geo_ensure_started = False

    # -- lifecycle -----------------------------------------------------------------------------

    def start(self) -> None:
        """Restore what the change tracker and the schedule remember, then start the worker."""
        with self._lock:
            if self._worker is not None:
                return
            for target in self.targets.list():
                recent = self.traces.latest(target.id, SEED_TRACES, status=None)
                self.tracker.seed(target.id, [t for t in recent if t.mode != "ping"])
                if recent:
                    self._last_started[target.id] = recent[0].started_ms
            self._worker = threading.Thread(target=self._work, name="geotrace-worker", daemon=True)
            self._worker.start()

    def stop(self, wait_s: float = STOP_WAIT_S) -> None:
        """Stop within about ``wait_s`` seconds in all.

        A run in flight is told to give up (at its next hop, ping or before saving) and then saves nothing and
        raises no event. A traceroute probe or ping already on the wire finishes first, so the worker thread
        may outlive the wait briefly; it is a daemon and does nothing more once it returns."""
        deadline = time.monotonic() + wait_s
        self._stopping.set()
        self.geo.cancel()  # a download must not write into files_dir once the plugin is gone
        self.queue.close()
        worker = self._worker
        if worker is not None:
            worker.join(max(deadline - time.monotonic(), 0.0))
        self.geo.stop(max(deadline - time.monotonic(), 0.0))
        self.geo.close()

    def _work(self) -> None:
        while not self._stopping.is_set():
            item = self.queue.get(1.0)
            if item is None:
                continue
            trace_id, job = item
            if self._stopping.is_set():
                self.queue.fail(trace_id, "NetView is shutting down")
                break
            live = self.queue.live(trace_id)
            saved = 0
            try:
                if live is not None:
                    saved = self._runner.run(job, live).id
            except Exception:
                self._ctx.log.exception("GeoTrace worker failed")
                if live is not None:
                    live.update(status="failed", error="internal error")
            finally:
                self.queue.finish(trace_id, saved)

    # -- jobs ----------------------------------------------------------------------------------

    def tick(self) -> None:
        """Queue every target that is due."""
        now = self._ctx.clock.now_ms()
        targets = {t.id: t for t in self.targets.list()}
        with self._lock:
            last = dict(self._last_started)
        for target_id in due_targets(list(targets.values()), last, now, self._invalid_interval):
            self._enqueue(targets[target_id], "scheduled", False)

    def cleanup(self) -> None:
        now = self._ctx.clock.now_ms()
        self.traces.delete_older(now - self.settings.retention_days * DAY_MS, now - ONCE_KEEP_DAYS * DAY_MS)

    def update_geo(self, force: bool = False) -> None:
        """Blocks on network I/O: only call it from a job or request thread."""
        self.geo.update(force)

    def settings_changed(self, settings: GeoTraceSettings) -> None:
        self.settings = settings

    # -- used by the routes -----------------------------------------------------------------

    def home(self) -> Home | None:
        s = self.settings
        if s.home_lat is None or s.home_lon is None:
            return None
        return Home(s.home_lat, s.home_lon, s.home_label)

    def ensure_geo_once(self) -> None:
        """Start fetching the location files on a background thread, once, if they are missing.

        Only when ``geo_auto_update`` is on and the city or ASN file is absent. Never blocks the caller."""
        if not self.settings.geo_auto_update or self._stopping.is_set():
            return
        status = self.geo.status()
        if status.get("city") and status.get("asn"):
            return
        with self._lock:
            if self._geo_ensure_started:
                return
            self._geo_ensure_started = True
        threading.Thread(target=self._ensure_geo, name="geotrace-geo-ensure", daemon=True).start()

    def _ensure_geo(self) -> None:
        try:
            self.geo.ensure()
        except Exception:
            self._ctx.log.exception("GeoTrace could not fetch its location data")

    def add_target(self, name: str, address: str, family: str, interval_min: int, enabled: bool) -> Target:
        _check_interval(interval_min)
        with self._lock:
            if self.targets.count() >= MAX_TARGETS:
                raise TargetLimitError
            return self.targets.add(name, address, family, interval_min, enabled, self._ctx.clock.now_ms())

    def update_target(self, target_id: int, **fields: Any) -> Target | None:
        if "interval_min" in fields:
            _check_interval(fields["interval_min"])
        return self.targets.update(target_id, updated_ms=self._ctx.clock.now_ms(), **fields)

    def remove_target(self, target_id: int) -> bool:
        """Delete a target with its traces, its waiting job and what is remembered about it."""
        self.queue.drop(target_id)
        deleted = self.targets.delete(target_id)
        self.tracker.forget(target_id)
        with self._lock:
            self._last_started.pop(target_id, None)
            self._warned.discard(target_id)
        return deleted

    def trace_now(self, target_id: int) -> int:
        """Queue a manual trace at the front; the id of the one already queued or running if there is one."""
        target = self.targets.get(target_id)
        if target is None:
            raise LookupError(f"no target {target_id}")
        return self._enqueue(target, "manual", True)

    def trace_once(self, address: str, family: str, mode: str) -> int:
        """Queue a one-off trace of an address that is not saved as a target."""
        job = Job(None, address, family, "once", mode, address)
        return self._put(job, True)[0]

    def live(self, trace_id: int) -> LiveTrace | None:
        return self.queue.live(trace_id)

    def resolve_id(self, trace_id: int) -> int | None:
        return self.queue.resolve_id(trace_id)

    # -- internals ---------------------------------------------------------------------------

    def _invalid_interval(self, target: Target) -> None:
        with self._lock:
            first = target.id not in self._warned
            self._warned.add(target.id)
        if first:
            self._ctx.log.warning(
                "GeoTrace target %s has an invalid interval (%s min); skipped",
                target.name,
                target.interval_min,
            )

    def _locator(self) -> HopLocator | None:
        return self.geo.locator()

    def _enqueue(self, target: Target, trigger: str, front: bool) -> int:
        job = Job(target.id, target.address, target.family, trigger, "trace", target.name)
        trace_id, queued = self._put(job, front)
        if queued:
            with self._lock:
                self._last_started[target.id] = self._ctx.clock.now_ms()
        return trace_id

    def _put(self, job: Job, front: bool) -> tuple[int, bool]:
        """The provisional id, and whether this call queued it (False: one was already queued or running)."""
        for _ in range(3):  # a job that finishes between the two calls leaves room to queue a new one
            trace_id = self.queue.put(job, front)
            if trace_id is not None:
                return trace_id, True
            trace_id = self.queue.existing_id(job)
            if trace_id is not None:
                return trace_id, False
        raise RuntimeError("GeoTrace is shutting down")
