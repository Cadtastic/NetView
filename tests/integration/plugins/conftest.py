import re
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from netview.application.plugins.jobs import JobSpec
from netview.application.plugins.registry import CapabilityRegistry
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.infrastructure.plugins.discovery import DiscoveredPlugin, import_folder
from netview.infrastructure.plugins.host import PluginHost
from netview.sdk import Plugin
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeServiceProbes,
    FakeSnmpClient,
    FakeSystemInfo,
    FakeVendors,
    InMemoryMetrics,
    RecordingEventBus,
)


class RecordingScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def add(self, owner: str, spec: JobSpec) -> None:
        self.calls.append(("add", owner, spec.name))

    def remove_owner(self, owner: str) -> None:
        self.calls.append(("remove_owner", owner, ""))

    def run_now(self, owner: str, name: str) -> None:
        self.calls.append(("run_now", owner, name))

    def status(self) -> list[Any]:
        return []


class HostEnv:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.registry = CapabilityRegistry()
        self.scheduler = RecordingScheduler()
        self._sessions = sessionmaker(engine)

    def uow(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self._sessions)

    def context_factory(self, plugin_id: str, settings: Any) -> DefaultPluginContext:
        return DefaultPluginContext(
            plugin_id,
            settings,
            self.engine,
            FakeClock(),
            FakeNetworkTools(),
            FakeVendors(),
            InMemoryMetrics(),
            None,  # type: ignore[arg-type]
            RecordingEventBus(),
            FakeServiceProbes(),
            FakeSystemInfo(),
            FakeSnmpClient([]),
        )

    def host(
        self,
        classes: list[type[Plugin]],
        seeds: dict[str, dict[str, Any]] | None = None,
        extra: list[DiscoveredPlugin] | None = None,
        setup_timeout_s: float = 10.0,
        poller: Any = None,
        folder_bases: list[tuple[Path, int]] | None = None,
    ) -> PluginHost:
        discovered = [DiscoveredPlugin(f"test:{c.__name__}", c, None) for c in classes]
        return PluginHost(
            engine=self.engine,
            uow=self.uow,
            registry=self.registry,
            scheduler=self.scheduler,
            context_factory=self.context_factory,
            seeds=seeds or {},
            discovered=discovered + (extra or []),
            setup_timeout_s=setup_timeout_s,
            poller=poller,
            folder_bases=folder_bases or (),
        )


@pytest.fixture
def env(tmp_path: Any) -> HostEnv:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    return HostEnv(engine)


def import_folders(base: Path) -> list[DiscoveredPlugin]:
    """Import every plugin folder under ``base`` (no plugin.json needed), numbering them 1, 2, ..."""
    folders = sorted(p for p in base.iterdir() if p.is_dir() and (p / "__init__.py").is_file())
    return [import_folder(f, n) for n, f in enumerate(folders, 1)]


@pytest.fixture(autouse=True)
def _fresh_local_plugin_modules() -> None:
    """Folder plugins are numbered per test database; drop modules an earlier test left behind."""
    for name in [m for m in sys.modules if re.match(r"netview_local_plugins\.p\d+(\.|$)", m)]:
        del sys.modules[name]
