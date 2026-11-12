"""One merged view of the switch, built from the two poll groups."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .config import IgmpConfig, ManagementConfig, MirrorConfig, QosConfig, VlanConfig
from .port import PortStatus
from .switch import SwitchInfo

PollGroup = Literal["status", "config"]

GROUP_FIELDS: Mapping[PollGroup, tuple[str, ...]] = MappingProxyType(
    {
        "status": ("ports",),
        "config": ("info", "vlans", "qos", "igmp", "mirror", "management"),
    }
)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """``groups`` says which groups' fields hold real data; the other groups' fields are empty."""

    t_ms: int
    groups: frozenset[PollGroup]
    info: SwitchInfo | None
    ports: tuple[PortStatus, ...]
    vlans: VlanConfig | None
    qos: QosConfig | None
    igmp: IgmpConfig | None
    mirror: MirrorConfig | None
    management: ManagementConfig | None

    def port(self, n: int) -> PortStatus | None:
        return next((p for p in self.ports if p.port == n), None)
