"""Review fix I5: bootstrap wires the scheduler's on_job_finished to the state notifier."""

from pathlib import Path

from netview.bootstrap import build_container
from netview.infrastructure.settings import AppSettings


def test_job_finished_signals_the_notifier(tmp_path: Path) -> None:
    container = build_container(AppSettings(data_dir=tmp_path))
    hits: list[int] = []
    container.services.notifier.subscribe(lambda: hits.append(1))
    container.scheduler.on_job_finished("core", "scan", True)
    assert hits == [1]
    container.engine.dispose()
