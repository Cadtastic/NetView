"""Network tools port."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class PingResult:
    rtt_ms: float
    ttl: int | None


@dataclass(frozen=True)
class TcpResult:
    state: Literal["open", "closed", "filtered"]
    ms: float | None


@dataclass(frozen=True)
class TraceHop:
    n: int
    ip: str | None  # None for "* * *"
    rtts_ms: tuple[float | None, ...]  # up to 3; None for a probe that timed out


@dataclass(frozen=True)
class TraceResult:
    target: str
    hops: tuple[TraceHop, ...]
    reached: bool  # last hop's ip == target
    error: str | None = None  # plain words: "traceroute is not installed", "not an IP address", "timed out"


class NetworkTools(Protocol):
    def ping(self, ip: str, timeout_ms: int = 800) -> PingResult | None: ...
    def arp_table(self) -> dict[str, str]: ...
    def tcp_probe(self, ip: str, port: int, timeout_s: float = 1.0) -> TcpResult: ...
    def dns_query(self, server: str, name: str, timeout_s: float = 2.0) -> float | None: ...
    def local_ip(self) -> str: ...
    def default_gateway(self, local_ip: str) -> str | None: ...
    def hostname(self) -> str: ...
    def traceroute(
        self,
        ip: str,
        max_hops: int = 30,
        probe_timeout_ms: int = 1000,
        on_hop: Callable[[TraceHop], None] | None = None,
    ) -> TraceResult: ...
