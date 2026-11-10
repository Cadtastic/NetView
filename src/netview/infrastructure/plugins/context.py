"""The runtime context handed to each plugin."""

from __future__ import annotations

import collections
import logging
import threading
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
from netview.infrastructure.db.engine import make_plugin_engine

log = logging.getLogger(__name__)

HANDLER_QUEUE_SIZE = 1000


class _HandlerWorker:
    """One daemon thread per plugin that runs its event handlers in order.

    The queue holds at most ``HANDLER_QUEUE_SIZE`` events; when it is full the oldest is dropped
    (and logged), so a stuck handler can never slow the publisher down or grow memory.
    """

    def __init__(self, plugin_id: str) -> None:
        self._plugin_id = plugin_id
        self._queue: collections.deque[tuple[Callable[[DomainEvent], None], DomainEvent]] = (
            collections.deque()
        )
        self._wake = threading.Condition()
        self._closed = False
        self._dropped = 0
        self._thread = threading.Thread(target=self._run, name=f"netview-plugin-{plugin_id}", daemon=True)
        self._thread.start()

    def submit(self, handler: Callable[[DomainEvent], None], e: DomainEvent) -> None:
        with self._wake:
            if self._closed:
                return
            if len(self._queue) >= HANDLER_QUEUE_SIZE:
                self._queue.popleft()
                self._dropped += 1
                if self._dropped == 1 or self._dropped % 100 == 0:
                    log.warning(
                        "plugin %s is not keeping up with events; dropped %d so far",
                        self._plugin_id,
                        self._dropped,
                    )
            self._queue.append((handler, e))
            self._wake.notify()

    def close(self) -> None:
        with self._wake:
            self._closed = True
            self._queue.clear()
            self._wake.notify_all()

    def _run(self) -> None:
        while True:
            with self._wake:
                while not self._queue and not self._closed:
                    self._wake.wait()
                if self._closed:
                    return
                handler, e = self._queue.popleft()
            try:
                handler(e)
            except Exception:
                log.exception("plugin %s event handler failed for %s", self._plugin_id, e.kind)


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
        self._worker: _HandlerWorker | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        # a dedicated engine whose connections may only write this plugin's own tables
        self._engine = make_plugin_engine(engine.url, plugin_id)
        self._sessions = sessionmaker(self._engine)

    def unit_of_work(self) -> PluginUnitOfWork:
        return _SessionUnitOfWork(self._sessions)

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        """Handlers run on this plugin's own worker thread, never in the publisher's."""
        if self._worker is None:
            self._worker = _HandlerWorker(self.plugin_id)
        worker = self._worker

        def deliver(e: DomainEvent) -> None:
            worker.submit(handler, e)

        unsubscribe = self._bus.subscribe(deliver)
        self._unsubscribers.append(unsubscribe)
        return unsubscribe

    def close(self) -> None:
        """Stop the worker and release the plugin's connections. Never waits for a stuck handler."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._worker is not None:
            self._worker.close()
            self._worker = None
        self._engine.dispose()
