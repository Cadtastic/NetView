from ipaddress import IPv4Network

import pytest
from usecase_helpers import SELF_IP, World, seen

from netview.application.capabilities import Capability
from netview.application.plugins.jobs import JobSpec, JobStatus
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.usecases.health import WatchMonitor
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.nicknames import SetNickname
from netview.application.usecases.traffic import TrafficLedger
from netview.application.usecases.watches import AddWatch
from netview.domain.errors import NotFoundError
from netview.domain.inspection import InspectionReport
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.samples import TrafficReading
from netview.domain.watch import WatchState
from netview.sdk.testing.fakes import InMemoryMetrics

HOST = HostInfo("test-host", SELF_IP, "192.168.1.1", "192.168.1.0/24", "linux")
JOB = JobStatus("lan_discovery", "sweep", 1, True, None, 0, 2, False)
MAC = "aa:bb:cc:dd:ee:01"


class StubScheduler:
    def add(self, owner: str, spec: JobSpec) -> None: ...
    def remove_owner(self, owner: str) -> None: ...
    def run_now(self, owner: str, name: str) -> None: ...
    def status(self) -> list[JobStatus]:
        return [JOB]


def make(w: World, registry: CapabilityRegistry | None = None) -> GetNetworkState:
    return GetNetworkState(w.uow, registry or CapabilityRegistry(), StubScheduler(), lambda: HOST)


def test_state_display_name_prefers_nickname() -> None:
    w = World()
    w.record([seen("192.168.1.20", MAC)])
    ClaimIdentity(w.uow, w.bus)([NameClaim(MAC, "printer-host", "mDNS", 3, 5)])
    state = make(w)
    assert state().devices[0].display_name == "printer-host"
    SetNickname(w.uow, w.clock, w.bus)(MAC, "Jessi's Kindle")
    view = state().devices[0]
    assert view.display_name == "Jessi's Kindle"
    assert view.nickname == "Jessi's Kindle"
    assert (view.device_name, view.name_source) == ("printer-host", "mDNS")


def test_state_sorts_by_ip_numeric() -> None:
    w = World()
    w.record([seen("192.168.1.10", "aa:bb:cc:dd:ee:10"), seen("192.168.1.2", "aa:bb:cc:dd:ee:02")])
    assert [d.ip for d in make(w)().devices] == ["192.168.1.2", "192.168.1.10"]


def test_state_marks_watched() -> None:
    w = World()
    w.record([seen("192.168.1.2", "aa:bb:cc:dd:ee:02"), seen("192.168.1.3", "aa:bb:cc:dd:ee:03")])
    AddWatch(w.uow, w.bus, w.clock)("192.168.1.2=Router")
    state = make(w)()
    assert [(d.ip, d.watched) for d in state.devices] == [("192.168.1.2", True), ("192.168.1.3", False)]
    assert state.devices[0].display_name == "Router"
    assert [x.ip for x in state.watches] == ["192.168.1.2"]


def test_state_type_hints_capabilities_jobs_and_events() -> None:
    w = World()
    w.record([seen("192.168.1.2", MAC)])
    ClaimIdentity(w.uow, w.bus)(
        [
            TypeClaim(MAC, "router", "ttl", "a"),
            Hint(MAC, "UPnP gateway", "a"),
            TypeClaim(MAC, "ap", "ssid", "b"),
        ]
    )
    registry = CapabilityRegistry()
    registry.register("p", Capability.DISCOVERY, object())
    state = make(w, registry)()
    assert state.devices[0].type == "ap"
    assert state.devices[0].hints == ["UPnP gateway"]
    assert state.capabilities == ["discovery"]
    assert state.jobs == [JOB]
    assert state.host == HOST
    assert state.events[0].kind.value == "type"


def test_state_with_no_devices() -> None:
    state = make(World())()
    assert state.devices == [] and state.capabilities == []


def test_get_device_returns_view_or_raises() -> None:
    w = World()
    w.record([seen("192.168.1.2", MAC)])
    get = GetDevice(w.uow)
    assert get(MAC).ip == "192.168.1.2"
    with pytest.raises(NotFoundError):
        get("aa:bb:cc:dd:ee:99")


def test_state_shows_the_type_source_and_prefers_inspection() -> None:
    w = World()
    w.record([seen("192.168.1.2", MAC)])
    claim = ClaimIdentity(w.uow, w.bus)
    claim([TypeClaim(MAC, "Roku device", "oui", "vendor", 5)])
    view = make(w)().devices[0]
    assert (view.type, view.type_source) == ("Roku device", "vendor")
    claim([TypeClaim(MAC, "TV", "ports", "inspection", 1)])
    view = make(w)().devices[0]
    assert (view.type, view.type_source) == ("TV", "inspection")


def test_state_without_a_type_has_an_empty_source() -> None:
    w = World()
    w.record([seen("192.168.1.2", MAC)])
    assert make(w)().devices[0].type_source == ""


def test_state_carries_watch_status_traffic_and_inspected() -> None:
    w = World()
    w.record([seen("192.168.1.2", MAC)])
    AddWatch(w.uow, w.bus, w.clock)("192.168.1.2=Router")
    ledger = TrafficLedger(InMemoryMetrics())
    ledger.record("starlink", [TrafficReading("192.168.1.2", 1, 0, 0, {})])
    with w.uow() as uow:
        uow.inspections.save(InspectionReport("192.168.1.2", "top", 10, 4242, []))
        uow.inspections.save(InspectionReport("192.168.1.2", "top", 10, 5555, []))
        uow.commit()
    state = GetNetworkState(
        w.uow,
        CapabilityRegistry(),
        StubScheduler(),
        lambda: HOST,
        monitor=WatchMonitor(w.uow, w.bus, w.clock),
        ledger=ledger,
        subnet=lambda: IPv4Network("192.168.1.0/24"),
    )()
    assert [(s.ip, s.state, s.label) for s in state.watch_status] == [
        ("192.168.1.2", WatchState.PENDING, "Router")
    ]
    assert [t.ip for t in state.traffic] == ["192.168.1.2"]
    assert [t.source for t in state.traffic_totals] == ["starlink"]
    assert state.inspected == {"192.168.1.2": 5555}


def test_state_without_monitor_and_ledger_has_empty_lists() -> None:
    state = make(World())()
    assert (state.watch_status, state.traffic, state.traffic_totals, state.inspected) == ([], [], [], {})
