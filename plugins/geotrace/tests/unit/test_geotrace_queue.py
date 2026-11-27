from __future__ import annotations

import threading
from dataclasses import replace

from netview_local_plugins.geotrace.model import Target
from netview_local_plugins.geotrace.queue import TraceQueue, due_targets
from netview_local_plugins.geotrace.runner import Job

MIN = 60_000
T0 = 1_800_000_000_000


def target(id: int, interval: int = 15, enabled: bool = True, created: int = T0) -> Target:
    return Target(id, f"t{id}", "example.test", "ipv4", interval, enabled, created, created)


def job(target_id: int | None = 1, address: str = "example.test", mode: str = "trace") -> Job:
    return Job(target_id, address, "ipv4", "scheduled", mode, "t")


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> int:
        return self.now


def test_hash_offsets_spread_ten_targets_across_the_interval() -> None:
    targets = [target(i) for i in range(1, 11)]
    due_at = {}
    for minute in range(0, 15):
        for tid in due_targets(targets, {}, T0 + minute * MIN):
            due_at.setdefault(tid, minute)
    assert sorted(due_at) == list(range(1, 11))  # every target comes due within one interval
    assert len(set(due_at.values())) >= 6  # ... and not all at once


def test_a_new_target_is_not_due_before_its_offset_and_is_due_after() -> None:
    t = target(7)
    assert due_targets([t], {}, T0 + 15 * MIN) == [7]
    first = next(m for m in range(0, 16) if due_targets([t], {}, T0 + m * MIN))
    assert due_targets([t], {}, T0 + (first - 1) * MIN) == [] if first else True


def test_after_a_start_the_target_is_due_every_interval() -> None:
    t = target(1, interval=15)
    last = {1: T0}
    assert due_targets([t], last, T0 + 14 * MIN) == []
    assert due_targets([t], last, T0 + 15 * MIN) == [1]


def test_overdue_after_a_restart_appears_once() -> None:
    t = target(1, interval=5)
    assert due_targets([t], {1: T0}, T0 + 24 * 60 * MIN) == [1]


def test_disabled_targets_are_never_due() -> None:
    assert due_targets([target(1, enabled=False)], {}, T0 + 24 * 60 * MIN) == []


def test_put_for_a_queued_target_returns_none_and_exposes_the_id() -> None:
    q = TraceQueue(Clock())
    first = q.put(job(1))
    assert first is not None and first < 0
    assert q.put(job(1)) is None
    assert q.running_for(1) == first
    assert q.put(job(2)) not in (None, first)


def test_a_running_target_also_refuses_a_second_put() -> None:
    q = TraceQueue(Clock())
    first = q.put(job(1))
    got = q.get(0.1)
    assert got is not None and got[0] == first
    assert q.put(job(1)) is None and q.running_for(1) == first
    q.finish(first, 5)
    assert q.running_for(1) is None
    assert q.put(job(1)) not in (None, first)


def test_front_jumps_the_queue() -> None:
    q = TraceQueue(Clock())
    a, b = q.put(job(1)), q.put(job(2))
    c = q.put(job(3), front=True)
    order = [q.get(0.1) for _ in range(3)]
    assert [o[0] for o in order if o] == [c, a, b]


def test_get_times_out_empty_and_wakes_on_put() -> None:
    q = TraceQueue(Clock())
    assert q.get(0.01) is None
    result: list[tuple[int, Job] | None] = []
    t = threading.Thread(target=lambda: result.append(q.get(5)))
    t.start()
    pid = q.put(job(1))
    t.join(5)
    assert result and result[0] is not None and result[0][0] == pid


def test_close_wakes_a_waiting_get() -> None:
    q = TraceQueue(Clock())
    result: list[object] = ["unset"]
    t = threading.Thread(target=lambda: result.__setitem__(0, q.get(30)))
    t.start()
    q.close()
    t.join(5)
    assert not t.is_alive() and result == [None]


def test_provisional_id_resolves_to_the_saved_id() -> None:
    q = TraceQueue(Clock())
    pid = q.put(job(1))
    assert pid is not None
    assert q.resolve_id(pid) is None  # not saved yet
    live = q.live(pid)
    assert live is not None and live.id == pid and live.snapshot().status == "queued"
    q.get(0.1)
    q.finish(pid, 42)
    assert q.resolve_id(pid) == 42
    assert q.resolve_id(42) == 42
    assert q.resolve_id(-999) is None


def test_an_unsaved_trace_stays_available_for_ten_minutes() -> None:
    clock = Clock()
    q = TraceQueue(clock)
    pid = q.put(job(None, "once.test"))
    assert pid is not None
    q.get(0.1)
    live = q.live(pid)
    assert live is not None
    live.update(status="failed", error="could not save")
    q.finish(pid, 0)
    assert q.resolve_id(pid) is None
    clock.now += 9 * MIN
    kept = q.live(pid)
    assert kept is not None and kept.snapshot().error == "could not save"
    clock.now += 2 * MIN
    assert q.live(pid) is None


def test_once_jobs_are_deduplicated_by_what_they_trace() -> None:
    q = TraceQueue(Clock())
    first = q.put(job(None, "a.test"))
    assert q.put(job(None, "A.test")) is None
    assert q.existing_id(job(None, "a.test")) == first
    assert q.put(job(None, "b.test")) is not None
    assert q.put(job(None, "a.test", mode="ping")) is not None


def test_close_fails_the_jobs_still_waiting() -> None:
    q = TraceQueue(Clock())
    pid = q.put(job(1))
    assert pid is not None
    q.close()
    live = q.live(pid)
    assert live is not None and live.snapshot().status == "failed"
    assert q.put(job(2)) is None


def test_front_moves_a_pending_duplicate_to_the_front_as_manual() -> None:
    q = TraceQueue(Clock())
    a = q.put(job(1))
    b = q.put(job(2))
    c = q.put(job(3))
    assert q.put(replace(job(3), trigger="manual"), front=True) is None
    assert q.existing_id(job(3)) == c
    first = q.get(0.1)
    assert first is not None and first[0] == c and first[1].trigger == "manual"
    assert [q.get(0.1)[0] for _ in range(2)] == [a, b]  # type: ignore[index]


def test_front_leaves_a_running_job_alone() -> None:
    q = TraceQueue(Clock())
    a = q.put(job(1))
    q.put(job(2))
    q.get(0.1)  # a is running
    assert q.put(replace(job(1), trigger="manual"), front=True) is None
    nxt = q.get(0.1)
    assert nxt is not None and nxt[0] != a


def test_a_finished_entry_releases_its_live_trace_but_the_mapping_resolves() -> None:
    clock = Clock()
    q = TraceQueue(clock)
    pid = q.put(job(1))
    assert pid is not None
    q.get(0.1)
    q.finish(pid, 42)
    assert q.live(pid) is not None
    clock.now += 11 * MIN
    assert q.live(pid) is None
    assert q._finished[pid].live is None
    assert q.resolve_id(pid) == 42
    clock.now += 25 * 60 * MIN
    assert q.resolve_id(pid) is None
    assert pid not in q._finished


def test_pruning_does_not_scan_unexpired_entries() -> None:
    clock = Clock()
    q = TraceQueue(clock)
    for i in range(50):
        pid = q.put(job(i))
        q.get(0.1)
        q.finish(pid, i + 1)  # type: ignore[arg-type]
    assert len(q._live_expiry) == 50 and len(q._map_expiry) == 50
    clock.now += 11 * MIN
    q.live(-1)
    assert len(q._live_expiry) == 0 and len(q._map_expiry) == 50


def test_drop_removes_a_pending_job_and_fails_its_live_trace() -> None:
    q = TraceQueue(Clock())
    a, b = q.put(job(1)), q.put(job(2))
    assert q.drop(1) is True
    assert q.running_for(1) is None
    live = q.live(a)  # type: ignore[arg-type]
    assert live is not None and live.snapshot().status == "failed"
    nxt = q.get(0.1)
    assert nxt is not None and nxt[0] == b
    assert q.drop(2) is False  # running: not dropped


def test_due_targets_skips_an_invalid_interval_and_reports_it() -> None:
    bad = target(1, interval=0)
    odd = target(2, interval=7)
    seen: list[int] = []
    assert due_targets([bad, odd, target(3)], {}, T0 + 24 * 60 * MIN, lambda t: seen.append(t.id)) == [3]
    assert seen == [1, 2]
