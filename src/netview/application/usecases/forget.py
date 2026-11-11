"""Forget a device: delete it and what was learned about it, but keep its nickname."""

from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWorkFactory
from netview.application.usecases._display import LabelResolver
from netview.domain.errors import NotFoundError, ValidationError
from netview.domain.events import DomainEvent, EventKind
from netview.domain.keys import SELF_KEY


class ForgetDevice:
    """User-only command. The nickname and its history stay, so a returning device gets its name back."""

    def __init__(self, uow: UnitOfWorkFactory, bus: EventBus, clock: Clock) -> None:
        self._uow = uow
        self._bus = bus
        self._clock = clock

    def __call__(self, key: str) -> None:
        if key == SELF_KEY:
            raise ValidationError("this device cannot be forgotten")
        with self._uow() as uow:
            device = uow.devices.get(key)
            if device is None:
                raise NotFoundError(f"no device with key {key!r}")
            name = LabelResolver(uow).label(key, device.ip) or device.ip
            uow.devices.remove(key)
            uow.identity.remove(key)
            event = DomainEvent(
                EventKind.FORGOTTEN, f"{name} forgotten", self._clock.now_ms(), device.ip, key
            )
            uow.events.add(event)
            uow.commit()
        self._bus.publish(event)
