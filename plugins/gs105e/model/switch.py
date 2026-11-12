"""Identity and network settings of the switch."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SwitchInfo:
    product: str
    name: str
    serial: str
    mac: str
    bootloader: str
    firmware: str
    dhcp: bool
    ip: str
    mask: str
    gateway: str
