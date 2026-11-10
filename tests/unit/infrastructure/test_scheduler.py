import asyncio
import time

from netview.application.plugins.jobs import JobSpec
from netview.infrastructure.scheduler import AsyncScheduler, next_delay
from netview.sdk.testing.fakes import FakeClock


def _run(coro):
    return asyncio.run(coro)


def test_job_runs_repeatedly() -> None:
    async def scenario() -> int:
        count = 0

        def tick() -> None:
            nonlocal count
            count += 1

        s = AsyncScheduler(FakeClock())
        s.add("p", JobSpec("tick", 0.05, tick))
        await s.start()
        await asyncio.sleep(0.4)
        await s.stop()
        return count

    assert _run(scenario()) >= 3


def test_async_job_is_awaited() -> None:
    async def scenario() -> int:
        count = 0

        async def tick() -> None:
            nonlocal count
            count += 1

        s = AsyncScheduler(FakeClock())
        s.add("p", JobSpec("tick", 0.05, tick))
        await s.start()
        await asyncio.sleep(0.3)
        await s.stop()
        return count

    assert _run(scenario()) >= 2


def test_hanging_job_times_out_and_others_continue() -> None:
    async def scenario():
        count = 0

        def hang() -> None:
            time.sleep(2)

        def tick() -> None:
            nonlocal count
            count += 1

        s = AsyncScheduler(FakeClock())
        s.add("p", JobSpec("hang", 0.05, hang, timeout_s=0.1))
        s.add("p", JobSpec("count", 0.05, tick))
        await s.start()
        await asyncio.sleep(0.5)
        status = {j.name: j for j in s.status()}
        await s.stop()
        return count, status

    count, status = _run(scenario())
    assert count >= 3
    hang = status["hang"]
    assert hang.last_ok is False
    assert hang.last_error is not None and "timeout" in hang.last_error
    assert hang.consecutive_failures == 1  # later ticks skipped while the thread still runs


def test_raising_job_is_marked_failed_and_recovers() -> None:
    async def scenario():
        calls = 0

        def flaky() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")

        s = AsyncScheduler(FakeClock())
        s.add("p", JobSpec("flaky", 0.05, flaky))
        await s.start()
        await asyncio.sleep(0.03)
        first = s.status()[0]
        await asyncio.sleep(0.3)
        later = s.status()[0]
        await s.stop()
        return first, later

    first, later = _run(scenario())
    assert first.last_ok is False and "boom" in (first.last_error or "")
    assert first.consecutive_failures == 1
    assert later.last_ok is True and later.consecutive_failures == 0


def test_backoff_after_three_failures() -> None:
    delays = [next_delay(1, n) for n in range(0, 6)]
    assert delays == [1, 1, 1, 2, 4, 8]
    assert next_delay(1, 50) == 300.0
    assert next_delay(600, 5) == 600  # never below the interval itself


def test_remove_owner_stops_jobs() -> None:
    async def scenario():
        count = 0

        def tick() -> None:
            nonlocal count
            count += 1

        s = AsyncScheduler(FakeClock())
        s.add("p", JobSpec("tick", 0.05, tick))
        s.add("q", JobSpec("other", 10, lambda: None, initial_delay_s=10))
        await s.start()
        await asyncio.sleep(0.2)
        s.remove_owner("p")
        await asyncio.sleep(0.05)
        frozen = count
        await asyncio.sleep(0.25)
        owners = {j.owner for j in s.status()}
        await s.stop()
        return frozen, count, owners

    frozen, final, owners = _run(scenario())
    assert final == frozen
    assert owners == {"q"}


def test_run_now_triggers_immediate_run() -> None:
    async def scenario() -> int:
        count = 0

        def tick() -> None:
            nonlocal count
            count += 1

        s = AsyncScheduler(FakeClock())
        s.add("p", JobSpec("tick", 100, tick, initial_delay_s=100))
        await s.start()
        await asyncio.sleep(0.05)
        s.run_now("p", "tick")
        await asyncio.sleep(0.2)
        await s.stop()
        return count

    assert _run(scenario()) == 1
