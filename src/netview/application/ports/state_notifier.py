"""State-changed signal port: "something a client may want to refetch has changed"."""

from collections.abc import Callable
from typing import Protocol


class StateNotifier(Protocol):
    def state_changed(self) -> None:
        """Signal that the network state may have changed. Safe to call from any thread."""
        ...

    def subscribe(self, handler: Callable[[], None]) -> Callable[[], None]:
        """Returns an unsubscribe function. The handler may be called from any thread."""
        ...
