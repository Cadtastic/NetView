"""Stand-ins for the probe and system ports that answer "nothing found" to every question.

Used until the real adapters (``SystemServiceProbes``, ``SystemSystemInfo``) are wired in.
"""

from netview.application.ports.probes import DnsRecord, HttpProbe, NetbiosInfo, SsdpEntry
from netview.application.ports.system import TcpSocket, WifiInfo


class UnavailableServiceProbes:
    def reverse_dns(self, ip: str, timeout_s: float = 2.0) -> str:
        return ""

    def netbios(self, ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None:
        return None

    def mdns_query(self, ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]:
        return []

    def ssdp_search(self, target: str | None = None, timeout_s: float = 2.5) -> list[SsdpEntry]:
        return []

    def upnp_description(self, ip: str, location: str) -> dict[str, str]:
        return {}

    def http_probe(self, ip: str, port: int, tls: bool, timeout_s: float = 3.0) -> HttpProbe | None:
        return None

    def tcp_banner(self, ip: str, port: int, timeout_s: float = 2.0) -> bytes | None:
        return None


class UnavailableSystemInfo:
    def interface_bytes(self) -> tuple[int, int] | None:
        return None

    def wifi(self) -> WifiInfo | None:
        return None

    def tcp_sockets(self) -> list[TcpSocket]:
        return []
