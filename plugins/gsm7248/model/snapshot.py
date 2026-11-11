"""One merged view of the switch, built from the three poll groups."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .mac import MacEntry
from .port import Port
from .switch import Health, Inventory, SwitchInfo
from .vlan import LagGroup, StpPort, Vlan

PollGroup = Literal["status", "bridge", "topology"]

GROUP_FIELDS: Mapping[PollGroup, tuple[str, ...]] = MappingProxyType(
    {
        "status": ("info", "health", "ports"),
        "bridge": ("macs",),
        "topology": ("inventory", "vlans", "pvids", "stp", "lags"),
    }
)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """``groups`` says which groups' fields hold real data.

    An empty tuple in a group that was polled is real data (an empty MAC table, say).
    It never means "not polled".
    """

    t_ms: int
    groups: frozenset[PollGroup]
    info: SwitchInfo | None
    health: Health | None
    inventory: Inventory | None
    ports: tuple[Port, ...]
    macs: tuple[MacEntry, ...]
    vlans: tuple[Vlan, ...]
    pvids: tuple[tuple[int, int], ...]  # (if_index, pvid)
    stp: tuple[StpPort, ...]
    lags: tuple[LagGroup, ...]

    def port(self, if_index: int) -> Port | None:
        return next((p for p in self.ports if p.if_index == if_index), None)

    def port_by_name(self, name: str) -> Port | None:
        return next((p for p in self.ports if p.name == name), None)

    def pvid(self, if_index: int) -> int | None:
        return next((v for i, v in self.pvids if i == if_index), None)
