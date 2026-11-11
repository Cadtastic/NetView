"""Switch identity, inventory and health."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SwitchInfo:
    sys_name: str
    sys_descr: str
    object_id: str
    uptime_cs: int
    mac: str | None


@dataclass(frozen=True, slots=True)
class Inventory:
    model: str | None
    serial: str | None
    firmware: str | None


@dataclass(frozen=True, slots=True)
class Health:
    cpu_percent: float | None
    mem_free_kb: int | None
    mem_total_kb: int | None
