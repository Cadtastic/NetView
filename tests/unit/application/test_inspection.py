from collections.abc import Iterable

import pytest

from netview.application.capabilities import Capability
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.usecases.inspection import RunInspection
from netview.domain.device import Device, DeviceStatus
from netview.domain.errors import CapabilityUnavailableError
from netview.domain.events import EventKind
from netview.domain.inspection import ReportSection
from netview.sdk.testing.fakes import FakeClock, InMemoryUnitOfWorkFactory, RecordingEventBus


class _Good:
    def inspect(self, ip: str, ports_spec: str) -> Iterable[ReportSection]:
        return [ReportSection("good", "ports", "Ports", {"ip": ip, "spec": ports_spec})]


class _Bad:
    def inspect(self, ip: str, ports_spec: str) -> Iterable[ReportSection]:
        raise RuntimeError("scanner exploded")


def test_run_inspection_requires_provider() -> None:
    run = RunInspection(CapabilityRegistry(), InMemoryUnitOfWorkFactory(), FakeClock())
    with pytest.raises(CapabilityUnavailableError):
        run("192.168.1.10")


def test_run_inspection_collects_sections_and_errors() -> None:
    registry = CapabilityRegistry()
    registry.register("good", Capability.INSPECTION, _Good())
    registry.register("bad", Capability.INSPECTION, _Bad())
    uow = InMemoryUnitOfWorkFactory()
    report = RunInspection(registry, uow, FakeClock())("192.168.1.10", "80,443")
    assert report.ip == "192.168.1.10" and report.ports_spec == "80,443"
    assert [s.id for s in report.sections] == ["ports", "error"]
    err = report.sections[1]
    assert (err.plugin_id, err.title, err.data, err.error) == ("bad", "bad", {}, "scanner exploded")
    with uow() as u:
        assert u.inspections.latest("192.168.1.10") == report


def test_store_false_saves_nothing_and_writes_no_event() -> None:
    registry = CapabilityRegistry()
    registry.register("good", Capability.INSPECTION, _Good())
    uow = InMemoryUnitOfWorkFactory()
    bus = RecordingEventBus()
    report = RunInspection(registry, uow, FakeClock(), bus)("192.168.1.10", "common", store=False)
    assert [s.id for s in report.sections] == ["ports"]
    with uow() as u:
        assert u.inspections.latest("192.168.1.10") is None
        assert u.events.recent() == []
    assert bus.published == []


def test_store_true_writes_and_publishes_one_inspected_event() -> None:
    registry = CapabilityRegistry()
    registry.register("good", Capability.INSPECTION, _Good())
    uow = InMemoryUnitOfWorkFactory()
    bus = RecordingEventBus()
    clock = FakeClock()
    RunInspection(registry, uow, clock, bus)("192.168.1.10")
    with uow() as u:
        (event,) = u.events.recent()
    assert event.kind is EventKind.INSPECTED
    assert event.text == "Inspected 192.168.1.10"
    assert event.ip == "192.168.1.10" and event.t_ms == clock.now_ms()
    assert bus.published == [event]


def test_inspected_event_uses_the_display_name() -> None:
    registry = CapabilityRegistry()
    registry.register("good", Capability.INSPECTION, _Good())
    uow = InMemoryUnitOfWorkFactory()
    key = "aa:bb:cc:dd:ee:01"
    with uow() as u:
        u.devices.add(Device(key, "192.168.1.10", key, "", 1, 1, DeviceStatus.ONLINE))
        u.nicknames.set(key, "Printer")
        u.commit()
    bus = RecordingEventBus()
    RunInspection(registry, uow, FakeClock(), bus)("192.168.1.10")
    assert bus.published[0].text == "Inspected Printer"
    assert bus.published[0].key == key


def test_without_a_bus_the_event_is_still_stored() -> None:
    registry = CapabilityRegistry()
    registry.register("good", Capability.INSPECTION, _Good())
    uow = InMemoryUnitOfWorkFactory()
    RunInspection(registry, uow, FakeClock())("192.168.1.10")
    with uow() as u:
        assert [e.kind for e in u.events.recent()] == [EventKind.INSPECTED]


def test_an_error_section_is_saved_under_the_plugins_guid() -> None:
    registry = CapabilityRegistry()
    registry.register("7", Capability.INSPECTION, _Bad())  # the registry knows the plugin by its source_id
    run = RunInspection(registry, InMemoryUnitOfWorkFactory(), FakeClock(), guid_of={"7": "the-guid"}.get)  # type: ignore[arg-type]
    [err] = run("192.168.1.10", store=False).sections
    assert (err.plugin_id, err.title) == ("the-guid", "the-guid")
