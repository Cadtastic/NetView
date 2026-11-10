"""The runtime context handed to each plugin."""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import TracebackType
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from netview.application.plugins.context import PluginUnitOfWork
from netview.application.plugins.core_facade import CoreFacade
from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.metrics import MetricsStore
from netview.application.ports.network import NetworkTools
from netview.application.ports.vendor import VendorLookup
from netview.domain.events import DomainEvent


class _SessionUnitOfWork:
    """A session on the shared engine; closed on exit, rolled back unless committed."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session: Session = session_factory()
        self._committed = False

    def commit(self) -> None:
        self.session.commit()
        self._committed = True

    def __enter__(self) -> _SessionUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self._committed:
                self.session.rollback()
        finally:
            self.session.close()


class DefaultPluginContext:
    def __init__(
        self,
        plugin_id: str,
        settings: Any,
        engine: Engine,
        clock: Clock,
        net: NetworkTools,
        vendors: VendorLookup,
        metrics: MetricsStore,
        core: CoreFacade,
        bus: EventBus,
    ) -> None:
        self.plugin_id = plugin_id
        self.settings = settings
        self.log = logging.getLogger(f"netview.plugin.{plugin_id}")
        self.clock = clock
        self.net = net
        self.vendors = vendors
        self.metrics = metrics
        self.core = core
        self._bus = bus
        self._sessions = sessionmaker(engine)

    def unit_of_work(self) -> PluginUnitOfWork:
        return _SessionUnitOfWork(self._sessions)

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        return self._bus.subscribe(handler)
