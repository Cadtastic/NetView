"""The narrow core API handed to plugins. It deliberately has no nickname writer."""

from collections.abc import Sequence

from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWorkFactory
from netview.application.queries.read_models import DeviceView
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings, SweepSummary
from netview.domain.events import DomainEvent, EventKind
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.samples import Sighting
from netview.domain.watch import Watch


class CoreFacade:
    def __init__(
        self,
        state: GetNetworkState,
        device: GetDevice,
        uow: UnitOfWorkFactory,
        record: RecordSightings,
        claim: ClaimIdentity,
        scan: RunScan,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._state = state
        self._device = device
        self._uow = uow
        self._record = record
        self._claim = claim
        self._scan = scan
        self._bus = bus
        self._clock = clock

    def devices(self) -> list[DeviceView]:
        return self._state().devices

    def device(self, key: str) -> DeviceView:
        return self._device(key)

    def watches(self) -> list[Watch]:
        with self._uow() as uow:
            return uow.watches.list()

    def record_sightings(self, s: Sequence[Sighting], complete_sweep: bool = False) -> SweepSummary:
        return self._record(s, complete_sweep=complete_sweep)

    def claim(self, items: Sequence[NameClaim | TypeClaim | Hint]) -> None:
        self._claim(items)

    def add_event(self, kind: EventKind, text: str, ip: str | None = None) -> None:
        event = DomainEvent(kind, text, self._clock.now_ms(), ip)
        with self._uow() as uow:
            uow.events.add(event)
            uow.commit()
        self._bus.publish(event)

    def run_scan(self) -> SweepSummary:
        return self._scan()
