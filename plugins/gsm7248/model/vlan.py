"""VLANs, spanning-tree port states and link aggregation groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StpState = Literal["disabled", "blocking", "listening", "learning", "forwarding", "broken"]


@dataclass(frozen=True, slots=True)
class Vlan:
    vid: int
    name: str
    egress: frozenset[int]  # ifIndex values
    untagged: frozenset[int]  # ifIndex values


@dataclass(frozen=True, slots=True)
class StpPort:
    if_index: int
    state: StpState


@dataclass(frozen=True, slots=True)
class LagGroup:
    if_index: int
    name: str
    members: frozenset[int]
