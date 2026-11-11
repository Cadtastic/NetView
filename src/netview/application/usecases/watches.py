"""Add and remove watches."""

import time
from collections.abc import Callable

from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWorkFactory
from netview.domain.events import DomainEvent, EventKind
from netview.domain.watch import Watch, parse_watch_spec


class AddWatch:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        bus: EventBus,
        clock: Clock | None = None,
        forget: Callable[[str], None] | None = None,
    ) -> None:
        self._uow = uow
        self._bus = bus
        self._now = clock.now_ms if clock else _system_now_ms
        self._forget = forget  # called with the IP once the watch is stored: a new watch starts over

    def __call__(self, spec: str) -> Watch:
        watch = parse_watch_spec(spec)
        event = DomainEvent(EventKind.WATCH, f"Watching {watch.spec()}", self._now(), watch.ip)
        with self._uow() as uow:
            uow.watches.add(watch)
            uow.events.add(event)
            uow.commit()
        if self._forget is not None:
            self._forget(watch.ip)
        self._bus.publish(event)
        return watch


class RemoveWatch:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        bus: EventBus,
        clock: Clock | None = None,
        forget: Callable[[str], None] | None = None,
    ) -> None:
        self._uow = uow
        self._bus = bus
        self._now = clock.now_ms if clock else _system_now_ms
        self._forget = forget  # called with the IP once the watch is gone

    def __call__(self, ip: str) -> bool:
        with self._uow() as uow:
            if not uow.watches.remove(ip):
                return False
            event = DomainEvent(EventKind.WATCH, f"Stopped watching {ip}", self._now(), ip)
            uow.events.add(event)
            uow.commit()
        if self._forget is not None:
            self._forget(ip)
        self._bus.publish(event)
        return True


def _system_now_ms() -> int:
    return time.time_ns() // 1_000_000
