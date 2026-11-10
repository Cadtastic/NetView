"""In-memory, thread-safe event bus with an async stream for SSE."""

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Callable

from netview.domain.events import DomainEvent

log = logging.getLogger(__name__)

_QUEUE_SIZE = 1000


class InMemoryEventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: list[Callable[[DomainEvent], None]] = []
        self._streams: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[DomainEvent]]] = []

    def publish(self, e: DomainEvent) -> None:
        with self._lock:
            handlers = list(self._handlers)
            streams = list(self._streams)
        for handler in handlers:
            try:
                handler(e)
            except Exception:
                log.exception("event handler failed for %s", e.kind)
        for loop, queue in streams:
            with contextlib.suppress(RuntimeError):  # the subscriber's loop may be closed
                loop.call_soon_threadsafe(self._offer, queue, e)

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._handlers.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers:
                    self._handlers.remove(handler)

        return unsubscribe

    @staticmethod
    def _offer(queue: asyncio.Queue[DomainEvent], e: DomainEvent) -> None:
        if queue.full():
            queue.get_nowait()  # drop the oldest
        queue.put_nowait(e)

    async def stream(self) -> AsyncIterator[DomainEvent]:
        queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        entry = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._streams.append(entry)
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                if entry in self._streams:
                    self._streams.remove(entry)
