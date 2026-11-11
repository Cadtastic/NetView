"""Bridge forwarding-table entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MacStatus = Literal["learned", "self", "mgmt", "other"]


@dataclass(frozen=True, slots=True)
class MacEntry:
    mac: str  # lower-case, colon-separated
    vlan: int
    if_index: int | None
    status: MacStatus
