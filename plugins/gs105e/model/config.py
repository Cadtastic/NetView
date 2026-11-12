"""Configuration pages: VLAN, QoS, IGMP, mirroring and management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VlanMode = Literal["off", "basic_8021q", "advanced_8021q", "basic_port", "advanced_port"]
QosMode = Literal["port", "dot1p"]
ManagementMode = Literal["web", "web_and_utility"]


@dataclass(frozen=True, slots=True)
class VlanMembers:
    """One code per port: "U" untagged, "T" tagged, "" not a member, "?x" an unknown character x."""

    vid: int
    members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VlanConfig:
    mode: VlanMode
    vlan_ids: tuple[int, ...]
    shown: VlanMembers | None
    pvids: tuple[tuple[int, int], ...]  # (port, pvid)


@dataclass(frozen=True, slots=True)
class RateLimit:
    """``None`` means no limit."""

    port: int
    ingress_kbps: int | None
    egress_kbps: int | None


@dataclass(frozen=True, slots=True)
class QosConfig:
    mode: QosMode
    rate_limits: tuple[RateLimit, ...]
    storm_control: bool


@dataclass(frozen=True, slots=True)
class IgmpConfig:
    enabled: bool
    vlan: int | None
    validate_v3_header: bool
    block_unknown: bool
    router_port: str | None


@dataclass(frozen=True, slots=True)
class MirrorConfig:
    enabled: bool
    destination: int | None
    sources: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ManagementConfig:
    mode: ManagementMode
    tftp: bool
    access_list: tuple[tuple[str, str], ...]
    power_saving: bool
    loop_detection: bool
