"""What a plugin sees at runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol

from netview.application.ports.clock import Clock
from netview.application.ports.metrics import MetricsStore
from netview.application.ports.network import NetworkTools
from netview.application.ports.probes import ServiceProbes
from netview.application.ports.system import SystemInfo
from netview.application.ports.vendor import VendorLookup
from netview.domain.events import DomainEvent

if TYPE_CHECKING:
    # Defined in a later task; only needed for type checking.
    from netview.application.plugins.core_facade import CoreFacade


class PluginUnitOfWork(Protocol):
    session: Any
    """A SQLAlchemy Session at runtime."""

    def commit(self) -> None: ...
    def __enter__(self) -> PluginUnitOfWork: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class PluginContext(Protocol):
    plugin_id: str
    settings: Any
    log: logging.Logger
    clock: Clock
    net: NetworkTools
    probes: ServiceProbes
    system: SystemInfo
    vendors: VendorLookup
    metrics: MetricsStore
    core: CoreFacade

    def unit_of_work(self) -> PluginUnitOfWork: ...
    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]: ...
