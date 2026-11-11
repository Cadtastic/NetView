import logging
from ipaddress import IPv4Network

import pytest
from test_state import StubScheduler
from usecase_helpers import SELF_IP, World, seen

from netview.application.capabilities import Capability
from netview.application.plugins.core_facade import CoreFacade
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.queries.read_models import HostInfo
from netview.application.queries.state import GetDevice, GetNetworkState
from netview.application.usecases.identity import ClaimIdentity
from netview.application.usecases.scan import RunScan
from netview.application.usecases.sightings import RecordSightings
from netview.domain.errors import NoNetworkError
from netview.domain.events import EventKind
from netview.domain.naming import NameClaim
from netview.domain.samples import Sighting


class OneShotDiscovery:
    def discover(self, subnet: IPv4Network) -> list[Sighting]:
        return [seen("192.168.1.7", "aa:bb:cc:dd:ee:07")]


def make(w: World, record: RecordSightings | None = None) -> CoreFacade:
    registry = CapabilityRegistry()
    registry.register("lan", Capability.DISCOVERY, OneShotDiscovery())
    host = HostInfo("h", SELF_IP, None, "192.168.1.0/24", "linux")
    return CoreFacade(
        GetNetworkState(w.uow, registry, StubScheduler(), lambda: host),
        GetDevice(w.uow),
        w.uow,
        record or w.record,
        ClaimIdentity(w.uow, w.bus),
        RunScan(registry, record or w.record, lambda: IPv4Network("192.168.1.0/24"), logging.getLogger("t")),
        w.bus,
        w.clock,
    )


def test_core_facade_has_no_nickname_writer() -> None:
    public = {n for n in dir(CoreFacade) if not n.startswith("_")}
    assert public == {"devices", "device", "watches", "record_sightings", "claim", "add_event", "run_scan"}


def test_facade_sightings_claim_and_read() -> None:
    w = World()
    facade = make(w)
    summary = facade.record_sightings([seen("192.168.1.2", "aa:bb:cc:dd:ee:02")])
    assert summary.seen == 1
    facade.claim([NameClaim("aa:bb:cc:dd:ee:02", "nas", "mDNS", 3, 5)])
    assert facade.device("aa:bb:cc:dd:ee:02").display_name == "nas"
    assert [d.ip for d in facade.devices()] == ["192.168.1.2"]
    assert facade.watches() == []


def test_facade_add_event_stores_and_publishes() -> None:
    w = World()
    make(w).add_event(EventKind.PLUGIN, "hello", "192.168.1.2")
    assert [e.text for e in w.bus.published] == ["hello"]
    assert w.bus.published[0].t_ms == w.clock.now_ms()
    with w.uow() as uow:
        assert [e.text for e in uow.events.recent()] == ["hello"]


def test_facade_run_scan_goes_through_discovery() -> None:
    w = World()
    facade = make(w)
    assert facade.run_scan().seen == 1
    assert [d.ip for d in facade.devices()] == ["192.168.1.7"]


def test_facade_record_sightings_without_a_lan_address_raises_and_stores_nothing() -> None:
    w = World()
    facade = make(w, RecordSightings(w.uow, w.clock, w.vendors, w.bus, lambda: "127.0.0.1"))
    with pytest.raises(NoNetworkError):
        facade.record_sightings([seen("192.168.1.2", "aa:bb:cc:dd:ee:02")])
    with w.uow() as uow:
        assert uow.devices.list() == []
    assert w.bus.published == []
