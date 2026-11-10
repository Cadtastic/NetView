"""Asyncio job scheduler with timeouts, no-overlap and failure backoff."""

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, cast

from netview.application.plugins.jobs import JobSpec, JobStatus
from netview.application.ports.clock import Clock

log = logging.getLogger(__name__)

_MAX_BACKOFF_S = 300.0


def next_delay(interval_s: float, failures: int) -> float:
    """Delay before the next run given the consecutive failure count."""
    if failures < 3:
        return interval_s
    return float(min(interval_s * 2 ** (failures - 2), max(interval_s, _MAX_BACKOFF_S)))


@dataclass
class _Job:
    owner: str
    spec: JobSpec
    last_run_ms: int | None = None
    last_ok: bool | None = None
    last_error: str | None = None
    failures: int = 0
    next_run_ms: int | None = None
    running: bool = False
    wake: asyncio.Event | None = None
    task: "asyncio.Task[None] | None" = field(default=None, repr=False)


class AsyncScheduler:
    def __init__(self, clock: Clock, max_workers: int = 32) -> None:
        self._clock = clock
        self._max_workers = max_workers
        self._jobs: dict[tuple[str, str], _Job] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="netview-job")
        for job in list(self._jobs.values()):
            self._spawn(job)

    async def stop(self) -> None:
        tasks = [j.task for j in self._jobs.values() if j.task is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        for j in self._jobs.values():
            j.task = None
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = None
        self._loop = None

    # --- Scheduler port -------------------------------------------------

    def add(self, owner: str, spec: JobSpec) -> None:
        key = (owner, spec.name)
        old = self._jobs.pop(key, None)
        if old is not None:
            self._cancel(old)
        job = _Job(owner, spec)
        self._jobs[key] = job
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._spawn, job)

    def remove_owner(self, owner: str) -> None:
        for key in [k for k in self._jobs if k[0] == owner]:
            self._cancel(self._jobs.pop(key))

    def run_now(self, owner: str, name: str) -> None:
        job = self._jobs.get((owner, name))
        if job is None or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._wake, job)

    def status(self) -> list[JobStatus]:
        return [
            JobStatus(
                owner=j.owner,
                name=j.spec.name,
                last_run_ms=j.last_run_ms,
                last_ok=j.last_ok,
                last_error=j.last_error,
                consecutive_failures=j.failures,
                next_run_ms=j.next_run_ms,
                running=j.running,
            )
            for j in list(self._jobs.values())
        ]

    # --- internals ------------------------------------------------------

    def _cancel(self, job: _Job) -> None:
        task = job.task
        if task is None:
            return
        if self._loop is not None:
            self._loop.call_soon_threadsafe(task.cancel)
        else:
            task.cancel()

    @staticmethod
    def _wake(job: _Job) -> None:
        if job.wake is not None:
            job.wake.set()

    def _spawn(self, job: _Job) -> None:
        if job.task is not None or self._jobs.get((job.owner, job.spec.name)) is not job:
            return
        job.wake = asyncio.Event()
        job.task = asyncio.create_task(self._loop_job(job), name=f"job:{job.owner}:{job.spec.name}")

    async def _sleep(self, job: _Job, delay_s: float) -> None:
        assert job.wake is not None
        job.next_run_ms = self._clock.now_ms() + int(delay_s * 1000)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(job.wake.wait(), timeout=delay_s)
        job.wake.clear()

    async def _loop_job(self, job: _Job) -> None:
        spec = job.spec
        await self._sleep(job, spec.initial_delay_s)
        while True:
            if not job.running:  # a timed-out sync run may still occupy its thread: skip this tick
                await self._run_once(job)
            await self._sleep(job, next_delay(spec.interval_s, job.failures))

    async def _run_once(self, job: _Job) -> None:
        spec = job.spec
        loop = asyncio.get_running_loop()
        job.running = True
        job.last_run_ms = self._clock.now_ms()
        job.next_run_ms = None
        is_async = inspect.iscoroutinefunction(spec.run)
        fut: asyncio.Future[Any]
        try:
            if is_async:
                fut = asyncio.ensure_future(cast(Awaitable[Any], spec.run()))
            else:
                fut = loop.run_in_executor(self._executor, spec.run)
        except Exception as exc:  # e.g. executor already shut down
            job.running = False
            self._fail(job, f"{type(exc).__name__}: {exc}")
            return
        fut.add_done_callback(lambda _f: self._finished(job))
        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=spec.timeout_s)
        except asyncio.CancelledError:
            if is_async:
                fut.cancel()
            raise
        except TimeoutError:
            if is_async:
                fut.cancel()
            self._fail(job, f"timeout after {spec.timeout_s}s")
        except Exception as exc:
            self._fail(job, f"{type(exc).__name__}: {exc}")
        else:
            job.last_ok = True
            job.last_error = None
            job.failures = 0

    @staticmethod
    def _finished(job: _Job) -> None:
        job.running = False

    @staticmethod
    def _fail(job: _Job, error: str) -> None:
        job.last_ok = False
        job.last_error = error
        job.failures += 1
        log.warning("job %s/%s failed: %s", job.owner, job.spec.name, error)
