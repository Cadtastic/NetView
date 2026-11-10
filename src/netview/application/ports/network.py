"""Network tools port."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class PingResult:
    rtt_ms: float
    ttl: int


@dataclass(frozen=True)
class TcpResult:
    state: Literal["open", "closed", "filtered"]
    ms: float | None


class NetworkTools(Protocol):
    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None: ...
    def arp_table(self) -> dict[str, str]: ...
    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult: ...
    def dns_query(self, server: str, name: str, timeout_s: float = 2.0) -> float | None: ...
    def local_ip(self) -> str: ...
    def default_gateway(self, local_ip: str) -> str | None: ...
    def hostname(self) -> str: ...
