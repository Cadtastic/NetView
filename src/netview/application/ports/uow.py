"""Unit of work port."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol

from netview.application.ports.repositories import (
    DeviceRepository,
    EventRepository,
    IdentityRepository,
    InspectionRepository,
    NicknameRepository,
    PluginRegistryRepository,
    PluginStateRepository,
    WatchRepository,
)


class UnitOfWork(Protocol):
    devices: DeviceRepository
    identity: IdentityRepository
    nicknames: NicknameRepository
    watches: WatchRepository
    events: EventRepository
    inspections: InspectionRepository
    plugin_state: PluginStateRepository
    plugin_registry: PluginRegistryRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Rolls back if nothing was committed."""
        ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
