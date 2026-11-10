"""Inspection report model."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReportSection:
    plugin_id: str
    id: str
    title: str
    data: Mapping[str, Any]
    error: str | None = None


@dataclass
class InspectionReport:
    ip: str
    ports_spec: str
    started_ms: int
    finished_ms: int
    sections: list[ReportSection]
