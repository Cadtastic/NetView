"""Review fixes on the SQL side: I7 isolation, M13 clear_new, forgetting a device."""

import contextlib
import threading
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from netview.application.ports.uow import UnitOfWorkFactory
from netview.application.usecases.forget import ForgetDevice
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.sightings import RecordSightings
from netview.domain.device import Device, DeviceStatus
from netview.domain.events import EventKind
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.samples import Sighting
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.sdk.testing.fakes import FakeClock, RecordingEventBus

MAC = "90:39:5f:00:00:01"
NEW_MAC = "aa:bb:cc:00:00:09"
SELF_IP = "192.168.1.95"


@pytest.fixture
def factory(tmp_path: Path) -> UnitOfWorkFactory:
    engine = make_engine(f"sqlite:///{tmp_path / 'review.db'}")
    upgrade_core(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return lambda: SqlUnitOfWork(sessions)


class _RendezvousVendors:
    """Makes two concurrent sweeps both decide the device is new before either writes."""

    def __init__(self) -> None:
        self.barrier = threading.Barrier(2)

    def vendor(self, mac: str | None) -> str:
        if mac == NEW_MAC:
            with contextlib.suppress(threading.BrokenBarrierError):
                self.barrier.wait(timeout=1.0)
        return ""


def test_two_threads_recording_the_same_new_device_do_not_collide(factory: UnitOfWorkFactory) -> None:
    clock, bus = FakeClock(), RecordingEventBus()
    record = RecordSightings(factory, clock, _RendezvousVendors(), bus, lambda: SELF_IP)
    record([Sighting("192.168.1.10", MAC, 1.0, 64, 1000)])  # the first sweep is over
    errors: list[BaseException] = []

    def sweep() -> None:
        try:
            record(
                [
                    Sighting("192.168.1.10", MAC, 1.0, 64, 2000),
                    Sighting("192.168.1.9", NEW_MAC, 1.0, 64, 2000),
                ]
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=sweep) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    with factory() as uow:
        assert [e.kind for e in uow.events.recent()].count(EventKind.NEW) == 1
        assert len([d for d in uow.devices.list() if d.key == NEW_MAC]) == 1


def test_clear_new(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.devices.add(Device(MAC, "192.168.1.10", MAC, "", 1, 2, DeviceStatus.ONLINE, is_new=True))
        uow.devices.add(Device(NEW_MAC, "192.168.1.11", NEW_MAC, "", 1, 2, DeviceStatus.ONLINE, is_new=True))
        uow.commit()
    with factory() as uow:
        uow.devices.clear_new()
        uow.commit()
    with factory() as uow:
        assert not any(d.is_new for d in uow.devices.list())


def test_forget_device_on_sql(factory: UnitOfWorkFactory) -> None:
    clock, bus = FakeClock(), RecordingEventBus()
    record = RecordSightings(factory, clock, _RendezvousVendors(), bus, lambda: SELF_IP)
    record([Sighting("192.168.1.10", MAC, 1.0, 64, 1000)])
    SetNickname(factory, clock, bus)(MAC, "Desk lamp")
    ClaimIdentity(factory, bus)(
        [NameClaim(MAC, "lamp", "DNS", 1, 5), TypeClaim(MAC, "iot", "oui", "a"), Hint(MAC, "hint", "a")]
    )
    ForgetDevice(factory, bus, clock)(MAC)
    with factory() as uow:
        assert uow.devices.get(MAC) is None
        assert uow.identity.claims(MAC) == [] and uow.identity.types(MAC) == []
        assert uow.identity.hints(MAC) == []
        assert uow.nicknames.get(MAC) == "Desk lamp"
        assert len(uow.nicknames.history(MAC)) == 1
        assert uow.events.recent()[0].kind is EventKind.FORGOTTEN
