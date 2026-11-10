from netview.domain.device import Device, DeviceStatus
from netview.domain.events import DomainEvent, EventKind
from netview.domain.nickname import NicknameChange
from netview.sdk.testing.fakes import (
    FakeClock,
    FakeNetworkTools,
    InMemoryMetrics,
    InMemoryUnitOfWorkFactory,
    RecordingEventBus,
)


def _device(key: str = "aa:bb:cc:dd:ee:ff") -> Device:
    return Device(key, "192.168.1.5", key, "V", 1, 1, DeviceStatus.ONLINE)


def test_uncommitted_add_is_not_visible_to_a_fresh_uow() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.devices.add(_device())
        assert uow.devices.get("aa:bb:cc:dd:ee:ff") is not None
    with factory() as uow:
        assert uow.devices.get("aa:bb:cc:dd:ee:ff") is None
        assert uow.devices.list() == []


def test_committed_add_is_visible() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.devices.add(_device())
        uow.nicknames.set("aa:bb:cc:dd:ee:ff", "Kindle")
        uow.nicknames.add_history(NicknameChange("aa:bb:cc:dd:ee:ff", "", "Kindle", "user", 5))
        uow.commit()
    with factory() as uow:
        assert uow.devices.get_by_ip("192.168.1.5") is not None
        assert uow.nicknames.all() == {"aa:bb:cc:dd:ee:ff": "Kindle"}
        assert len(uow.nicknames.history()) == 1


def test_explicit_rollback_discards_changes() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.devices.add(_device())
        uow.rollback()
    with factory() as uow:
        assert uow.devices.list() == []


def test_rekey_moves_nickname() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.nicknames.set("ip:192.168.1.5", "Box")
        uow.nicknames.rekey("ip:192.168.1.5", "aa:bb:cc:dd:ee:ff")
        uow.commit()
    with factory() as uow:
        assert uow.nicknames.all() == {"aa:bb:cc:dd:ee:ff": "Box"}


def test_fake_clock_advances() -> None:
    clock = FakeClock()
    start = clock.now_ms()
    clock.advance(250)
    assert clock.now_ms() == start + 250


def test_fake_network_fail_mode() -> None:
    net = FakeNetworkTools(arp={"192.168.1.2": "aa:aa:aa:aa:aa:aa"}, replies={}, fail=True)
    assert net.ping("192.168.1.2") is None
    assert net.arp_table() == {}


def test_event_bus_and_metrics() -> None:
    bus = RecordingEventBus()
    seen: list[DomainEvent] = []
    unsubscribe = bus.subscribe(seen.append)
    e = DomainEvent(EventKind.NEW, "x", 1)
    bus.publish(e)
    unsubscribe()
    bus.publish(e)
    assert bus.published == [e, e]
    assert seen == [e]

    m = InMemoryMetrics()
    m.append("lat.a", 1, 1.0)
    m.append("lat.a", 2, None)
    m.append("other", 3, 2.0)
    assert m.series("lat.a") == [(1, 1.0), (2, None)]
    assert m.names("lat.") == ["lat.a"]
