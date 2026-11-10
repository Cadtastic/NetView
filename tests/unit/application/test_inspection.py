from collections.abc import Iterable

import pytest

from netview.application.capabilities import Capability
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.usecases.inspection import RunInspection
from netview.domain.errors import CapabilityUnavailableError
from netview.domain.inspection import ReportSection
from netview.sdk.testing.fakes import FakeClock, InMemoryUnitOfWorkFactory


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
