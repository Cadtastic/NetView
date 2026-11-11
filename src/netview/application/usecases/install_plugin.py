"""Install a plugin from the catalog as a background job."""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from netview.application.plugins.plugin_json import installable
from netview.application.ports.plugin_admin import PluginAdmin
from netview.application.ports.plugin_catalog import PluginInstaller
from netview.application.usecases.plugin_catalog import PluginCatalogService
from netview.domain.errors import ConflictError, NotFoundError, ValidationError

JobState = Literal["queued", "downloading", "installing", "done", "failed"]
_ACTIVE: tuple[JobState, ...] = ("queued", "downloading", "installing")


@dataclass
class InstallJob:
    id: str
    plugin_id: str
    state: JobState
    percent: int | None = None
    error: str | None = None


class InstallJobs:
    def __init__(
        self,
        catalog: PluginCatalogService,
        installer: PluginInstaller,
        admin: PluginAdmin,
        submit: Callable[[Callable[[], None]], None],
        sdk_version: str,
        has_package: Callable[[str], bool],
    ) -> None:
        self._catalog = catalog
        self._installer = installer
        self._admin = admin
        self._submit = submit
        self._sdk_version = sdk_version
        self._has_package = has_package
        self._jobs: dict[str, InstallJob] = {}
        self._lock = threading.Lock()

    def start(self, plugin_id: str) -> InstallJob:
        entry = self._catalog.entry(plugin_id)  # NotFoundError when it is not listed
        if any(p.id == plugin_id for p in self._admin.list()):
            raise ConflictError(f"{entry.plugin.name} is already installed")
        reason = installable(entry.plugin, self._sdk_version, self._has_package)
        if reason is not None:
            raise ValidationError(reason)
        with self._lock:
            if any(j.plugin_id == plugin_id and j.state in _ACTIVE for j in self._jobs.values()):
                raise ConflictError(f"{entry.plugin.name} is already being installed")
            job = InstallJob(uuid.uuid4().hex, plugin_id, "queued")
            self._jobs[job.id] = job
            snapshot = replace(job)
        self._submit(lambda: self._run(job.id))
        return snapshot

    def get(self, job_id: str) -> InstallJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError(f"unknown install job {job_id!r}")
            return replace(job)

    def _update(
        self, job_id: str, state: JobState, percent: int | None = None, error: str | None = None
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = state
            job.percent = percent
            job.error = error

    def _run(self, job_id: str) -> None:
        with self._lock:
            plugin_id = self._jobs[job_id].plugin_id

        def progress(phase: str, percent: int | None) -> None:
            if phase == "downloading":
                self._update(job_id, "downloading", percent)
            else:
                self._update(job_id, "installing")

        try:
            entry = self._catalog.entry(plugin_id)
            index = self._catalog.index()
            if index is None:
                raise NotFoundError("no plugin catalog")
            self._installer.install(entry, index.archive_url, progress)
        except Exception as exc:  # the job records every failure for the UI
            text = str(exc).strip()
            self._update(job_id, "failed", error=text.splitlines()[0] if text else type(exc).__name__)
        else:
            self._update(job_id, "done")
