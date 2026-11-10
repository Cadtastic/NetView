"""Background job contracts."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class JobSpec:
    """A recurring job. ``run`` may be sync or async."""

    name: str
    interval_s: float
    run: Callable[[], object]
    timeout_s: float = 60.0
    initial_delay_s: float = 0.0


@dataclass
class JobStatus:
    owner: str
    name: str
    last_run_ms: int | None
    last_ok: bool | None
    last_error: str | None
    consecutive_failures: int
    next_run_ms: int | None
    running: bool


class Scheduler(Protocol):
    def add(self, owner: str, spec: JobSpec) -> None: ...
    def remove_owner(self, owner: str) -> None: ...
    def run_now(self, owner: str, name: str) -> None: ...
    def status(self) -> list[JobStatus]: ...
