"""Pure value types for the GSM7248 plugin. Standard library only."""

from .codec import snapshot_from_json, snapshot_to_json
from .mac import MacEntry, MacStatus
from .port import Duplex, Port, PortCounters, PortKind, PortRates
from .snapshot import GROUP_FIELDS, PollGroup, Snapshot
from .switch import Health, Inventory, SwitchInfo
from .vlan import LagGroup, StpPort, StpState, Vlan

__all__ = [
    "GROUP_FIELDS",
    "Duplex",
    "Health",
    "Inventory",
    "LagGroup",
    "MacEntry",
    "MacStatus",
    "PollGroup",
    "Port",
    "PortCounters",
    "PortKind",
    "PortRates",
    "Snapshot",
    "StpPort",
    "StpState",
    "SwitchInfo",
    "Vlan",
    "snapshot_from_json",
    "snapshot_to_json",
]
