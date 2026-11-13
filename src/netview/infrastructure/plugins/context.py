"""The runtime context handed to each plugin."""

from __future__ import annotations

import collections
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from netview.application.auth.principal import SYSTEM_PRINCIPAL, Principal, get_principal
from netview.application.plugins.context import PluginIdentity, PluginUnitOfWork
from netview.application.plugins.core_facade import CoreFacade
from netview.application.ports.audit import AuditEntry, AuditSink, NullAuditSink
from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.metrics import MetricsStore
from netview.application.ports.network import NetworkTools
from netview.application.ports.probes import ServiceProbes
from netview.application.ports.snmp import SnmpClient
from netview.application.ports.system import SystemInfo
from netview.application.ports.vendor import VendorLookup
from netview.domain.errors import PermissionDeniedError
from netview.domain.events import DomainEvent
from netview.infrastructure.db.engine import make_plugin_engine

log = logging.getLogger(__name__)

HANDLER_QUEUE_SIZE = 1000


def _noop() -> None:
    return None


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
        identity: PluginIdentity,
        settings: Any,
        data_file: Path | None,
        clock: Clock,
        net: NetworkTools,
        vendors: VendorLookup,
        metrics: MetricsStore,
        core: CoreFacade,
        bus: EventBus,
        probes: ServiceProbes,
        system: SystemInfo,
        snmp: SnmpClient,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.guid = identity.guid
        self.source_id = identity.source_id
        self.display_name = identity.display_name
        self.settings = settings
        self.log = logging.getLogger(f"netview.plugin.p{identity.source_id}")
        self.clock = clock
        self.net = net
        self.probes = probes
        self.system = system
        self.vendors = vendors
        self.metrics = metrics
        self.snmp = snmp
        self.core = core
        self._bus = bus
        self._audit_sink: AuditSink = audit_sink if audit_sink is not None else NullAuditSink()
        self._worker: _HandlerWorker | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._closed = False
        # the plugin's own database file; a plugin without storage has none
        self._engine: Engine | None = make_plugin_engine(data_file) if data_file is not None else None
        self._sessions = sessionmaker(self._engine) if self._engine is not None else None

    def unit_of_work(self) -> PluginUnitOfWork:
        if self._closed:
            raise RuntimeError("this plugin has been stopped")
        if self._sessions is None:
            raise RuntimeError("this plugin declares no storage")
        return _SessionUnitOfWork(self._sessions)

    def principal(self) -> Principal:
        """The caller of the current request; the system principal in a job or outside a request."""
        return get_principal() or SYSTEM_PRINCIPAL

    def require(self, permission_id: str) -> Any:
        """A FastAPI dependency that admits only holders of the permission (``core.*`` IDs pass through)."""
        full = permission_id if permission_id.startswith("core.") else f"{self.guid}.{permission_id}"

        def check() -> None:
            if not self.principal().can(full):
                raise PermissionDeniedError("You do not have permission to do that")

        # Read by the plugin router's default guard: a route with an explicit guard keeps only that one.
        check.__netview_permission__ = full  # type: ignore[attr-defined]
        return Depends(check)

    def audit(
        self, action: str, target: str | None = None, ok: bool = True, detail: str | None = None
    ) -> None:
        self._audit_sink.record(
            AuditEntry(
                t_ms=self.clock.now_ms(),
                username=self.principal().username,
                ip=None,
                action=action,
                target=target,
                outcome="ok" if ok else "failed",
                detail=detail,
            )
        )

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        """Handlers run on this plugin's own worker thread, never in the publisher's.

        After ``close()`` (a timed-out ``setup()`` thread may still call this) nothing is registered.
        """
        if self._closed:
            return _noop
        if self._worker is None:
            self._worker = _HandlerWorker(f"p{self.source_id}")
        worker = self._worker

        def deliver(e: DomainEvent) -> None:
            worker.submit(handler, e)

        unsubscribe = self._bus.subscribe(deliver)
        self._unsubscribers.append(unsubscribe)
        return unsubscribe

    def close(self) -> None:
        """Stop the worker and release the plugin's connections. Never waits for a stuck handler."""
        self._closed = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        if self._worker is not None:
            self._worker.close()
            self._worker = None
        if self._engine is not None:
            self._engine.dispose()
