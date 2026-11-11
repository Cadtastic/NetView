"""Run an inspection through every inspection provider and store the report."""

from typing import cast

from netview.application.capabilities import Capability, InspectionProvider
from netview.application.plugins.registry import CapabilityRegistry
from netview.application.ports.clock import Clock
from netview.application.ports.event_bus import EventBus
from netview.application.ports.uow import UnitOfWorkFactory
from netview.application.usecases._display import LabelResolver
from netview.domain.events import DomainEvent, EventKind
from netview.domain.inspection import InspectionReport, ReportSection


class RunInspection:
    def __init__(
        self,
        registry: CapabilityRegistry,
        uow: UnitOfWorkFactory,
        clock: Clock,
        bus: EventBus | None = None,
    ) -> None:
        self._registry = registry
        self._uow = uow
        self._clock = clock
        self._bus = bus

    def __call__(self, ip: str, ports_spec: str = "top", store: bool = True) -> InspectionReport:
        """Inspect ``ip``. With ``store=False`` the report is returned and nothing is saved or announced."""
        providers = self._registry.require(Capability.INSPECTION)
        started = self._clock.now_ms()
        sections: list[ReportSection] = []
        for plugin_id, provider in providers:
            try:
                sections.extend(cast(InspectionProvider, provider).inspect(ip, ports_spec))
            except Exception as exc:
                sections.append(ReportSection(plugin_id, "error", plugin_id, {}, error=str(exc)))
        report = InspectionReport(ip, ports_spec, started, self._clock.now_ms(), sections)
        if store:
            self._store(report)
        return report

    def _store(self, report: InspectionReport) -> None:
        with self._uow() as uow:
            uow.inspections.save(report)
            device = uow.devices.get_by_ip(report.ip)
            key = device.key if device is not None else None
            name = LabelResolver(uow).label(key, report.ip) if key is not None else ""
            event = DomainEvent(
                EventKind.INSPECTED, f"Inspected {name or report.ip}", report.finished_ms, report.ip, key
            )
            uow.events.add(event)
            uow.commit()
        if self._bus is not None:
            self._bus.publish(event)
