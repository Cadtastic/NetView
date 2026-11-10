"""Shared builders for use-case tests."""

from netview.application.usecases.sightings import RecordSightings
from netview.domain.samples import Sighting
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeVendors,
    InMemoryUnitOfWorkFactory,
    RecordingEventBus,
)

SELF_IP = "192.168.1.95"


class World:
    def __init__(self) -> None:
        self.uow = InMemoryUnitOfWorkFactory()
        self.clock = FakeClock()
        self.bus = RecordingEventBus()
        self.vendors = FakeVendors()
        self.record = RecordSightings(self.uow, self.clock, self.vendors, self.bus, lambda: SELF_IP)

    def kinds(self) -> list[str]:
        return [e.kind.value for e in self.bus.published]


def seen(ip: str, mac: str | None = None, rtt: float | None = 1.0, t: int = 1000) -> Sighting:
    return Sighting(ip, mac, rtt, 64 if rtt is not None else None, t)
