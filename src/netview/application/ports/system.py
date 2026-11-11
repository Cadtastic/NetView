"""System info port: this device's own counters, Wi-Fi link and sockets."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WifiInfo:
    ssid: str = ""
    bssid: str = ""
    signal_pct: int | None = None
    radio: str = ""
    band: str = ""
    channel: str = ""
    rx_rate_mbps: float | None = None
    tx_rate_mbps: float | None = None
    state: str = ""
    auth: str = ""


@dataclass(frozen=True)
class TcpSocket:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    state: str
    process: str


class SystemInfo(Protocol):
    def interface_bytes(self) -> tuple[int, int] | None:
        """Total ``(rx, tx)`` bytes across adapters, or ``None`` when they cannot be read."""
        ...

    def wifi(self) -> WifiInfo | None:
        """The current Wi-Fi link, or ``None`` when this device is not on Wi-Fi."""
        ...

    def tcp_sockets(self) -> list[TcpSocket]:
        """TCP sockets with process names resolved; NetView's own sockets are left out."""
        ...
