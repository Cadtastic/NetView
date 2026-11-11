from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from netview.application.ports.repositories import PluginState
from netview.application.ports.uow import UnitOfWorkFactory
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.sightings import RecordSightings
from netview.domain.device import Device, DeviceStatus
from netview.domain.events import DomainEvent, EventKind
from netview.domain.inspection import InspectionReport, ReportSection
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.nickname import NicknameChange
from netview.domain.samples import Sighting
from netview.domain.watch import Watch
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.sdk.testing.fakes import FakeClock, FakeVendors, InMemoryUnitOfWorkFactory, RecordingEventBus

MAC = "90:39:5f:00:00:01"
SELF_IP = "192.168.1.95"


@pytest.fixture
def sql_factory(tmp_path: Path) -> UnitOfWorkFactory:
    engine = make_engine(f"sqlite:///{tmp_path / 'netview.db'}")
    upgrade_core(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return lambda: SqlUnitOfWork(sessions)


def _device(key: str = MAC, ip: str = "192.168.1.10") -> Device:
    return Device(key, ip, MAC if key == MAC else None, "Acme", 100, 200, DeviceStatus.ONLINE, 1.5, 64)


def test_device_roundtrip(sql_factory: UnitOfWorkFactory) -> None:
    d = Device(MAC, "192.168.1.10", MAC, "Acme", 100, 200, DeviceStatus.QUIET, None, None, True, 3, True)
    with sql_factory() as uow:
        uow.devices.add(d)
        uow.commit()
    with sql_factory() as uow:
        assert uow.devices.get(MAC) == d
        assert uow.devices.get_by_ip("192.168.1.10") == d
        assert uow.devices.get("nope") is None
        d.status = DeviceStatus.OFFLINE
        d.missed = 4
        uow.devices.save(d)
        uow.commit()
    with sql_factory() as uow:
        (loaded,) = uow.devices.list()
        assert loaded.status is DeviceStatus.OFFLINE and loaded.missed == 4
        uow.devices.remove(MAC)
        uow.commit()
    with sql_factory() as uow:
        assert uow.devices.list() == []


def test_rekey_moves_nickname_and_claims(sql_factory: UnitOfWorkFactory) -> None:
    old = "ip:192.168.1.10"
    with sql_factory() as uow:
        uow.nicknames.set(old, "Box")
        uow.nicknames.add_history(NicknameChange(old, "", "Box", "user", 5))
        uow.identity.upsert_claim(NameClaim(old, "box.lan", "DNS", 1, 10))
        uow.identity.upsert_claim(NameClaim(MAC, "stale", "mDNS", 3, 1))
        uow.identity.upsert_type(TypeClaim(old, "printer", "port 9100", "inspection"))
        uow.identity.replace_hints(old, "dhcp", [Hint(old, "hint-a", "dhcp"), Hint(old, "hint-b", "dhcp")])
        uow.nicknames.rekey(old, MAC)
        uow.identity.rekey(old, MAC)
        uow.commit()
    with sql_factory() as uow:
        assert uow.nicknames.all() == {MAC: "Box"}
        assert [c.key for c in uow.nicknames.history()] == [MAC]
        assert {(c.name, c.source) for c in uow.identity.claims(MAC)} == {
            ("stale", "mDNS"),
            ("box.lan", "DNS"),
        }
        assert uow.identity.claims(old) == []
        assert [t.type for t in uow.identity.types(MAC)] == ["printer"]
        assert [h.text for h in uow.identity.hints(MAC)] == ["hint-a", "hint-b"]
        assert uow.identity.hints(old) == []


def test_rekey_does_not_overwrite_existing_nickname(sql_factory: UnitOfWorkFactory) -> None:
    with sql_factory() as uow:
        uow.nicknames.set("ip:1.1.1.1", "Old")
        uow.nicknames.set(MAC, "Keep")
        uow.nicknames.rekey("ip:1.1.1.1", MAC)
        uow.commit()
    with sql_factory() as uow:
        assert uow.nicknames.all() == {MAC: "Keep"}


def test_uncommitted_changes_rolled_back(sql_factory: UnitOfWorkFactory) -> None:
    with sql_factory() as uow:
        uow.devices.add(_device())
        uow.nicknames.set(MAC, "Gone")
    with sql_factory() as uow:
        assert uow.devices.list() == []
        assert uow.nicknames.all() == {}
    with sql_factory() as uow:
        uow.devices.add(_device())
        uow.rollback()
        uow.commit()
    with sql_factory() as uow:
        assert uow.devices.list() == []


def test_nickname_history_free_text_by(sql_factory: UnitOfWorkFactory) -> None:
    change = NicknameChange(MAC, "Auto", "", "claude: cleared auto-written nickname", 7)
    with sql_factory() as uow:
        uow.nicknames.add_history(change)
        uow.commit()
    with sql_factory() as uow:
        assert uow.nicknames.history(MAC) == [change]
        assert uow.nicknames.has_history(change)
        assert not uow.nicknames.has_history(NicknameChange(MAC, "Auto", "", "someone else", 7))


def test_other_repositories_roundtrip(sql_factory: UnitOfWorkFactory) -> None:
    report = InspectionReport(
        "192.168.1.10", "22,80", 1, 2, [ReportSection("p", "ports", "Ports", {"open": [22]}, None)]
    )
    with sql_factory() as uow:
        uow.watches.add(Watch("192.168.1.20", (80, 443), "NAS"))
        uow.watches.add(Watch("192.168.1.20", (22,), "NAS2"))
        uow.events.add(DomainEvent(EventKind.NEW, "first", 1, "192.168.1.10", MAC))
        uow.events.add(DomainEvent(EventKind.OFFLINE, "second", 2))
        uow.inspections.save(report)
        uow.plugin_state.save(PluginState("demo", False, {"a": 1}, "1.2.3"))
        uow.commit()
    with sql_factory() as uow:
        assert uow.watches.list() == [Watch("192.168.1.20", (22,), "NAS2")]
        assert uow.watches.remove("192.168.1.20") is True
        assert uow.watches.remove("192.168.1.20") is False
        assert [e.text for e in uow.events.recent()] == ["second", "first"]
        assert uow.events.recent(1)[0].ip is None
        assert uow.inspections.latest("192.168.1.10") == report
        assert uow.inspections.latest("9.9.9.9") is None
        assert uow.plugin_state.get("demo") == PluginState("demo", False, {"a": 1}, "1.2.3")
        assert uow.plugin_state.get("other") is None


# Contract parity: the same use-case behaviour on the fakes and on SQL.


@pytest.fixture(params=["memory", "sql"])
def factory(request: pytest.FixtureRequest, tmp_path: Path) -> UnitOfWorkFactory:
    if request.param == "memory":
        return InMemoryUnitOfWorkFactory()
    engine = make_engine(f"sqlite:///{tmp_path / 'parity.db'}")
    upgrade_core(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return lambda: SqlUnitOfWork(sessions)


def _record(factory: UnitOfWorkFactory) -> tuple[RecordSightings, FakeClock, RecordingEventBus]:
    clock, bus = FakeClock(), RecordingEventBus()
    return RecordSightings(factory, clock, FakeVendors(), bus, lambda: SELF_IP), clock, bus


def _seen(ip: str, mac: str | None = None) -> Sighting:
    return Sighting(ip, mac, 1.0, 64, 1000)


def test_parity_sightings_rekey_ip_device_to_mac(factory: UnitOfWorkFactory) -> None:
    """Review focus 1: ip:<ip> device gains a MAC; nickname moves, no duplicate row."""
    record, clock, bus = _record(factory)
    record([_seen("192.168.1.10")])
    SetNickname(factory, clock, bus)("ip:192.168.1.10", "Jessi's Kindle")
    record([_seen("192.168.1.10", MAC)])
    with factory() as uow:
        assert [d.key for d in uow.devices.list()] == [MAC]
        assert uow.nicknames.all() == {MAC: "Jessi's Kindle"}
        assert [c.key for c in uow.nicknames.history()] == [MAC]


def test_parity_sightings_offline_after_missed_sweeps(factory: UnitOfWorkFactory) -> None:
    record, _, bus = _record(factory)
    record([_seen("192.168.1.10", MAC)])
    record([])
    record([])
    assert [e.kind.value for e in bus.published] == ["offline"]
    with factory() as uow:
        d = uow.devices.get(MAC)
        assert d is not None and d.status is DeviceStatus.OFFLINE and d.missed == 2
        assert [e.kind for e in uow.events.recent()] == [EventKind.OFFLINE]


def _at(key: str, status: DeviceStatus, first: int, last: int, ip: str = "192.168.1.50") -> Device:
    return Device(key, ip, None, None, first, last, status, None, None)


def _owner(factory: UnitOfWorkFactory, *devices: Device) -> str | None:
    with factory() as uow:
        for d in devices:
            uow.devices.add(d)
        uow.commit()
    with factory() as uow:
        found = uow.devices.get_by_ip("192.168.1.50")
        return found.key if found is not None else None


def test_parity_by_ip_among_offline_rows_returns_the_newest_seen(factory: UnitOfWorkFactory) -> None:
    """DHCP churn leaves several offline rows on one address: the one seen last is the owner."""
    phone = _at("ip:phone", DeviceStatus.OFFLINE, first=100, last=500)
    laptop = _at("ip:laptop", DeviceStatus.OFFLINE, first=900, last=1500)
    assert _owner(factory, phone, laptop) == "ip:laptop"


def test_parity_by_ip_prefers_online_then_quiet_then_offline(factory: UnitOfWorkFactory) -> None:
    old_online = _at("ip:online", DeviceStatus.ONLINE, first=100, last=200)
    newer_quiet = _at("ip:quiet", DeviceStatus.QUIET, first=300, last=900)
    newest_offline = _at("ip:offline", DeviceStatus.OFFLINE, first=400, last=1900)
    assert _owner(factory, newest_offline, newer_quiet, old_online) == "ip:online"


def test_parity_by_ip_prefers_quiet_over_offline_and_the_newest_of_two_live_rows(
    factory: UnitOfWorkFactory,
) -> None:
    quiet = _at("ip:quiet", DeviceStatus.QUIET, first=100, last=300)
    offline = _at("ip:offline", DeviceStatus.OFFLINE, first=200, last=900)
    assert _owner(factory, offline, quiet) == "ip:quiet"


def test_parity_by_ip_among_live_rows_returns_the_newest_seen(factory: UnitOfWorkFactory) -> None:
    older = _at("ip:older", DeviceStatus.ONLINE, first=100, last=300)
    newer = _at("ip:newer", DeviceStatus.ONLINE, first=200, last=900)
    assert _owner(factory, older, newer) == "ip:newer"


@pytest.mark.parametrize("text", ["Café <b>", "Jessi's Kindle", "日本語"])
def test_parity_nickname_stored_exactly_and_cleared(factory: UnitOfWorkFactory, text: str) -> None:
    record, clock, bus = _record(factory)
    record([_seen("192.168.1.10", MAC)])
    set_nickname: Callable[..., str | None] = SetNickname(factory, clock, bus)
    assert set_nickname(MAC, text) == text
    clock.advance(10)
    set_nickname(MAC, None, by="claude: cleared auto-written nickname")
    with factory() as uow:
        assert uow.nicknames.get(MAC) is None
        newest, oldest = uow.nicknames.history(MAC)
        assert (oldest.new, newest.new, newest.by) == (text, "", "claude: cleared auto-written nickname")


MAC2 = "aa:bb:cc:00:00:02"
MAC3 = "aa:bb:cc:00:00:03"


def test_parity_conflict_event_survives_a_restart(factory: UnitOfWorkFactory) -> None:
    """Two RecordSightings instances on one database (a restart) report a conflict once."""
    first, _, _ = _record(factory)
    first([_seen("192.168.1.10", MAC)])
    first([_seen("192.168.1.10", MAC2)])
    restarted, _, _ = _record(factory)
    restarted([_seen("192.168.1.10", MAC2)])
    with factory() as uow:
        conflicts = [e for e in uow.events.recent() if e.kind is EventKind.CONFLICT]
        assert [(e.ip, e.key) for e in conflicts] == [("192.168.1.10", MAC2)]
        last = uow.events.last(EventKind.CONFLICT, "192.168.1.10")
        assert last is not None and last.key == MAC2
        assert uow.events.last(EventKind.CONFLICT, "192.168.1.99") is None
        assert uow.events.last(EventKind.NEW, "192.168.1.10") is not None


def test_parity_conflict_is_reported_again_for_a_different_new_owner(factory: UnitOfWorkFactory) -> None:
    record, _, _ = _record(factory)
    record([_seen("192.168.1.10", MAC)])
    record([_seen("192.168.1.10", MAC2)], complete_sweep=False)
    record([_seen("192.168.1.10", MAC3)], complete_sweep=False)
    with factory() as uow:
        keys = [e.key for e in reversed(uow.events.recent()) if e.kind is EventKind.CONFLICT]
    assert keys == [MAC2, MAC3]


def test_parity_type_claim_keeps_checked_ms(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.identity.upsert_type(TypeClaim(MAC, "printer", "port 9100", "inspection", 777))
        uow.identity.upsert_type(TypeClaim("other", "camera", "rtsp", "inspection"))
        uow.commit()
    with factory() as uow:
        assert uow.identity.types(MAC) == [TypeClaim(MAC, "printer", "port 9100", "inspection", 777)]
        assert uow.identity.all_types() == {
            MAC: [TypeClaim(MAC, "printer", "port 9100", "inspection", 777)],
            "other": [TypeClaim("other", "camera", "rtsp", "inspection", 0)],
        }


def test_parity_all_hints_groups_by_key_in_insertion_order(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.identity.replace_hints(MAC, "a", [Hint(MAC, "one", "a"), Hint(MAC, "two", "a")])
        uow.identity.replace_hints("other", "a", [Hint("other", "three", "a")])
        uow.commit()
    with factory() as uow:
        got = uow.identity.all_hints()
        assert [h.text for h in got[MAC]] == ["one", "two"]
        assert [h.text for h in got["other"]] == ["three"]


def test_inspection_latest_times(sql_factory: UnitOfWorkFactory) -> None:
    def report(ip: str, finished: int) -> InspectionReport:
        return InspectionReport(ip, "top", 1, finished, [])

    for factory in (sql_factory, InMemoryUnitOfWorkFactory()):
        with factory() as uow:
            assert uow.inspections.latest_times() == {}
            uow.inspections.save(report("192.168.1.10", 100))
            uow.inspections.save(report("192.168.1.10", 300))
            uow.inspections.save(report("192.168.1.11", 200))
            uow.commit()
        with factory() as uow:
            assert uow.inspections.latest_times() == {"192.168.1.10": 300, "192.168.1.11": 200}
