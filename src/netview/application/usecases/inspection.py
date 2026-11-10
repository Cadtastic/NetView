"""Run an inspection through every inspection provider and store the report."""

from typing import cast

from netview.application.capabilities import Capability, InspectionProvider
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.clock import Clock
from netview.application.ports.uow import UnitOfWorkFactory
from netview.domain.inspection import InspectionReport, ReportSection


class RunInspection:
    def __init__(self, registry: CapabilityRegistry, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._registry = registry
        self._uow = uow
        self._clock = clock

    def __call__(self, ip: str, ports_spec: str = "top") -> InspectionReport:
        providers = self._registry.require(Capability.INSPECTION)
        started = self._clock.now_ms()
        sections: list[ReportSection] = []
        for plugin_id, provider in providers:
            try:
                sections.extend(cast(InspectionProvider, provider).inspect(ip, ports_spec))
            except Exception as exc:
                sections.append(ReportSection(plugin_id, "error", plugin_id, {}, error=str(exc)))
        report = InspectionReport(ip, ports_spec, started, self._clock.now_ms(), sections)
        with self._uow() as uow:
            uow.inspections.save(report)
            uow.commit()
        return report
