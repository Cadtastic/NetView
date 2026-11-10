"""Set or clear a device nickname."""

from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWorkFactory
from netview.domain.errors import NotFoundError
from netview.domain.events import DomainEvent, EventKind
from netview.domain.nickname import NicknameChange, normalize_nickname


class SetNickname:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock, bus: EventBus) -> None:
        self._uow = uow
        self._clock = clock
        self._bus = bus

    def __call__(self, key: str, raw: str | None, by: str = "user") -> str | None:
        new = normalize_nickname(raw)
        with self._uow() as uow:
            device = uow.devices.get(key)
            if device is None:
                raise NotFoundError(f"no device with key {key!r}")
            old = uow.nicknames.get(key)
            if old == new:
                return new
            now = self._clock.now_ms()
            uow.nicknames.set(key, new)
            uow.nicknames.add_history(NicknameChange(key, old or "", new or "", by, now))
            if new:
                text = f"{device.ip} nickname set to {new}"
            else:
                text = f"{device.ip} nickname cleared (was {old})"
            event = DomainEvent(EventKind.NICKNAME, text, now, device.ip, key)
            uow.events.add(event)
            uow.commit()
        self._bus.publish(event)
        return new
