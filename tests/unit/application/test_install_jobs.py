from collections.abc import Callable

import pytest

from netview.application.plugins.plugin_json import (
    DEFAULT_ARCHIVE_URL,
    CatalogEntry,
    PluginIndex,
    PluginJson,
    build_index,
)
from netview.application.ports.plugin_admin import PluginInfo
from netview.application.ports.plugin_catalog import CatalogSnapshot, Progress
from netview.application.usecases.install_plugin import InstallJobs
from netview.application.usecases.plugin_catalog import PluginCatalogService
from netview.domain.errors import ConflictError, InstallError, NotFoundError, ValidationError
from netview.sdk.testing.fakes import FakeClock


def _pj(plugin_id: str, sdk_version: str = ">=1.3,<2") -> PluginJson:
    return PluginJson(plugin_id, plugin_id.title(), "0.1.0", "d", sdk_version, ("api",), ("api",))


class MemStore:
    def __init__(self, index: PluginIndex) -> None:
        self.snapshot: CatalogSnapshot | None = CatalogSnapshot(index, "bundled", None, None)

    def load(self) -> CatalogSnapshot | None:
        return self.snapshot

    def save(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot


class StubAdmin:
    def __init__(self) -> None:
        self.infos: list[PluginInfo] = []

    def list(self) -> list[PluginInfo]:
        return self.infos


class StubInstaller:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.seen: list[tuple[str, str]] = []
        self.states: list[str] = []
        self.jobs: InstallJobs | None = None
        self.job_id = ""

    def install(self, entry: CatalogEntry, archive_url: str, progress: Progress) -> None:
        self.seen.append((entry.plugin.id, archive_url))
        progress("downloading", 40)
        if self.jobs and self.job_id:
            self.states.append(self.jobs.get(self.job_id).state)
        progress("installing", None)
        if self.jobs and self.job_id:
            self.states.append(self.jobs.get(self.job_id).state)
        if self.error:
            raise self.error


class Harness:
    def __init__(self, run_inline: bool = True) -> None:
        self.admin = StubAdmin()
        self.installer = StubInstaller()
        self.queue: list[Callable[[], None]] = []
        index = build_index([_pj("alpha"), _pj("old", ">=9")], "main", DEFAULT_ARCHIVE_URL)
        catalog = PluginCatalogService(
            MemStore(index),
            None,  # type: ignore[arg-type]
            lambda: index,
            self.admin,  # type: ignore[arg-type]
            FakeClock(),
            "1.3",
            lambda name: True,
        )
        self.jobs = InstallJobs(
            catalog,
            self.installer,
            self.admin,  # type: ignore[arg-type]
            (lambda fn: fn()) if run_inline else self.queue.append,
            "1.3",
            lambda name: True,
        )
        self.installer.jobs = self.jobs


def test_start_unknown_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        Harness().jobs.start("nope")


def test_start_installed_is_conflict() -> None:
    h = Harness()
    h.admin.infos.append(PluginInfo("alpha", "Alpha", "1", "d", "active"))
    with pytest.raises(ConflictError):
        h.jobs.start("alpha")


def test_start_pending_is_conflict() -> None:
    h = Harness()
    h.admin.infos.append(PluginInfo("alpha", "Alpha", "1", "d", "pending"))
    with pytest.raises(ConflictError):
        h.jobs.start("alpha")


def test_start_not_installable_is_validation_error() -> None:
    with pytest.raises(ValidationError, match="Needs a newer netview"):
        Harness().jobs.start("old")


def test_second_start_same_id_is_conflict() -> None:
    h = Harness(run_inline=False)
    job = h.jobs.start("alpha")
    assert job.state == "queued"
    assert len(job.id) == 32
    with pytest.raises(ConflictError):
        h.jobs.start("alpha")
    h.queue.pop()()
    assert h.jobs.get(job.id).state == "done"


def test_job_states_flow_to_done() -> None:
    h = Harness(run_inline=False)
    job = h.jobs.start("alpha")
    h.installer.job_id = job.id
    h.queue.pop()()
    assert h.installer.states == ["downloading", "installing"]
    done = h.jobs.get(job.id)
    assert done.state == "done"
    assert done.error is None
    assert h.installer.seen == [("alpha", DEFAULT_ARCHIVE_URL)]


def test_job_failure_records_error() -> None:
    h = Harness()
    h.installer.error = InstallError("the plugin folder has no __init__.py\nsecond line")
    job = h.jobs.start("alpha")
    failed = h.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error == "the plugin folder has no __init__.py"


def test_get_unknown_job_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        Harness().jobs.get("nope")
