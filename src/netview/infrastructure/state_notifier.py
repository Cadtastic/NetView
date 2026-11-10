"""In-memory, thread-safe fan-out for the state-changed signal."""

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class InMemoryStateNotifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: list[Callable[[], None]] = []

    def state_changed(self) -> None:
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler()
            except Exception:
                log.exception("state handler failed")

    def subscribe(self, handler: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._handlers.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers:
                    self._handlers.remove(handler)

        return unsubscribe
