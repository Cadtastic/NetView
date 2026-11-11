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
from netview.infrastructure.plugins.discovery import DiscoveredPlugin
from netview.infrastructure.plugins.host import PluginHost
from netview.sdk import Plugin
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    FakeSnmpClient,
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
            FakeSnmpClient([]),
        )

    def host(
        self,
        classes: list[type[Plugin]],
        seeds: dict[str, dict[str, Any]] | None = None,
        extra: list[DiscoveredPlugin] | None = None,
        setup_timeout_s: float = 10.0,
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
        )


@pytest.fixture
def env(tmp_path: Any) -> HostEnv:
    engine = make_engine(f"sqlite:///{tmp_path / 'n.db'}")
    upgrade_core(engine)
    return HostEnv(engine)
