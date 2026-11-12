"""What a plugin sees at runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol

from netview.application.auth.principal import Principal
from netview.application.ports.clock import Clock
from netview.application.ports.metrics import MetricsStore
from netview.application.ports.network import NetworkTools
from netview.application.ports.probes import ServiceProbes
from netview.application.ports.snmp import SnmpClient
from netview.application.ports.system import SystemInfo
from netview.application.ports.vendor import VendorLookup
from netview.domain.events import DomainEvent

if TYPE_CHECKING:
    # Defined in a later task; only needed for type checking.
    from netview.application.plugins.core_facade import CoreFacade


@dataclass(frozen=True)
class PluginIdentity:
    """Who a plugin is: the host hands this to ``context_factory``."""

    guid: str
    source_id: int
    display_name: str
    legacy_id: str = ""
    """The author-written id. Only the core-db write fence and table prefix use it (to be removed)."""


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
    guid: str
    source_id: int
    display_name: str
    settings: Any
    log: logging.Logger
    clock: Clock
    net: NetworkTools
    probes: ServiceProbes
    system: SystemInfo
    vendors: VendorLookup
    metrics: MetricsStore
    snmp: SnmpClient
    core: CoreFacade

    def unit_of_work(self) -> PluginUnitOfWork: ...
    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]: ...

    def require(self, permission_id: str) -> Any:
        """A FastAPI ``Depends`` that lets only holders of the permission through (SDK 1.5).

        A relative ID gets ``<guid>.`` prepended; ``core.*`` IDs pass through unchanged.
        """
        ...

    def principal(self) -> Principal:
        """The caller of the current request, or the system principal outside a request."""
        ...

    def audit(
        self, action: str, target: str | None = None, ok: bool = True, detail: str | None = None
    ) -> None:
        """Record an audit entry for the current caller."""
        ...
