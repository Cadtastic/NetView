import uuid
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


def _guid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def _pj(plugin_id: str, sdk_version: str = ">=2.0,<3") -> PluginJson:
    return PluginJson(
        plugin_id.title(),
        "0.1.0",
        "d",
        _guid(plugin_id),
        plugin_id.title(),
        "other",
        sdk_version,
        ("api",),
        ("api",),
    )


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
        self.seen.append((entry.plugin.guid, archive_url))
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
        index = build_index(
            [CatalogEntry(_pj("alpha"), "plugins/alpha"), CatalogEntry(_pj("old", ">=9"), "plugins/old")],
            "main",
            DEFAULT_ARCHIVE_URL,
        )
        catalog = PluginCatalogService(
            MemStore(index),
            None,  # type: ignore[arg-type]
            lambda: index,
            self.admin,  # type: ignore[arg-type]
            FakeClock(),
            "2.0",
            lambda name: True,
        )
        self.jobs = InstallJobs(
            catalog,
            self.installer,
            self.admin,  # type: ignore[arg-type]
            (lambda fn: fn()) if run_inline else self.queue.append,
            "2.0",
            lambda name: True,
        )
        self.installer.jobs = self.jobs


def test_start_unknown_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        Harness().jobs.start(_guid("nope"))


def test_start_installed_is_conflict() -> None:
    h = Harness()
    h.admin.infos.append(PluginInfo("3", "Alpha", "1", "d", "active", guid=_guid("alpha")))
    with pytest.raises(ConflictError):
        h.jobs.start(_guid("alpha"))


def test_start_pending_is_conflict() -> None:
    h = Harness()
    h.admin.infos.append(PluginInfo("folder:x", "Alpha", "1", "d", "pending", guid=_guid("alpha")))
    with pytest.raises(ConflictError):
        h.jobs.start(_guid("alpha"))


def test_start_not_installable_is_validation_error() -> None:
    with pytest.raises(ValidationError, match="Needs a newer netview"):
        Harness().jobs.start(_guid("old"))


def test_second_start_same_guid_is_conflict() -> None:
    h = Harness(run_inline=False)
    job = h.jobs.start(_guid("alpha"))
    assert job.state == "queued"
    assert len(job.id) == 32
    with pytest.raises(ConflictError):
        h.jobs.start(_guid("alpha"))
    h.queue.pop()()
    assert h.jobs.get(job.id).state == "done"


def test_job_states_flow_to_done() -> None:
    h = Harness(run_inline=False)
    job = h.jobs.start(_guid("alpha"))
    h.installer.job_id = job.id
    h.queue.pop()()
    assert h.installer.states == ["downloading", "installing"]
    done = h.jobs.get(job.id)
    assert done.state == "done"
    assert done.error is None
    assert h.installer.seen == [(_guid("alpha"), DEFAULT_ARCHIVE_URL)]


def test_job_failure_records_error() -> None:
    h = Harness()
    h.installer.error = InstallError("the plugin folder has no __init__.py\nsecond line")
    job = h.jobs.start(_guid("alpha"))
    failed = h.jobs.get(job.id)
    assert failed.state == "failed"
    assert failed.error == "the plugin folder has no __init__.py"


def test_get_unknown_job_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        Harness().jobs.get("nope")
