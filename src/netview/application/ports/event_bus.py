"""Event bus port."""

from collections.abc import Callable
from typing import Protocol

from netview.domain.events import DomainEvent


class EventBus(Protocol):
    def publish(self, e: DomainEvent) -> None: ...
    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        """Returns an unsubscribe function."""
        ...
