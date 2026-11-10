"""Review fix I5: the scheduler reports finished jobs and the notifier fans signals out."""

import asyncio

from netview.application.plugins.jobs import JobSpec
from netview.infrastructure.scheduler import AsyncScheduler
from netview.infrastructure.state_notifier import InMemoryStateNotifier
from netview.sdk.testing.fakes import FakeClock


def test_on_job_finished_reports_success_and_failure() -> None:
    async def scenario() -> list[tuple[str, str, bool]]:
        seen: list[tuple[str, str, bool]] = []

        def boom() -> None:
            raise RuntimeError("x")

        s = AsyncScheduler(FakeClock(), on_job_finished=lambda o, n, ok: seen.append((o, n, ok)))
        s.add("p", JobSpec("good", 60.0, lambda: None))
        s.add("p", JobSpec("bad", 60.0, boom))
        await s.start()
        await asyncio.sleep(0.4)
        await s.stop()
        return seen

    seen = asyncio.run(scenario())
    assert ("p", "good", True) in seen
    assert ("p", "bad", False) in seen


def test_a_failing_hook_does_not_break_the_scheduler() -> None:
    async def scenario() -> int:
        count = 0

        def tick() -> None:
            nonlocal count
            count += 1

        def hook(owner: str, name: str, ok: bool) -> None:
            raise RuntimeError("hook")

        s = AsyncScheduler(FakeClock(), on_job_finished=hook)
        s.add("p", JobSpec("tick", 0.05, tick))
        await s.start()
        await asyncio.sleep(0.4)
        await s.stop()
        return count

    assert asyncio.run(scenario()) >= 3


def test_notifier_fans_out_and_unsubscribes() -> None:
    notifier = InMemoryStateNotifier()
    got: list[int] = []
    off = notifier.subscribe(lambda: got.append(1))
    notifier.state_changed()
    off()
    notifier.state_changed()
    assert got == [1]
