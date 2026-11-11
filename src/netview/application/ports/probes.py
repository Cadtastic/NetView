"""Service probes port: the network questions shared by identity and inspection plugins."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class DnsRecord:
    name: str
    rtype: int
    value: str | tuple[str, ...] | None


@dataclass(frozen=True)
class NetbiosName:
    name: str
    suffix: int
    group: bool


@dataclass(frozen=True)
class NetbiosInfo:
    name: str
    workgroup: str
    names: tuple[NetbiosName, ...]
    mac: str


@dataclass(frozen=True)
class SsdpEntry:
    ip: str
    location: str
    server: str
    usn: str
    st: tuple[str, ...]


@dataclass(frozen=True)
class CertInfo:
    sha256: str
    subject: str = ""
    subject_org: str = ""
    issuer: str = ""
    issuer_org: str = ""
    not_after: str = ""
    self_signed: bool = False
    san: tuple[str, ...] = ()


@dataclass(frozen=True)
class HttpProbe:
    scheme: Literal["http", "https"]
    url: str
    status: int | None
    reason: str
    server: str
    powered_by: str
    location: str
    title: str
    generator: str
    auth: str
    realm: str
    tls: str | None
    cert: CertInfo | None


class ServiceProbes(Protocol):
    """Read-only questions to one device. Everything that came back is untrusted text."""

    def reverse_dns(self, ip: str, timeout_s: float = 2.0) -> str: ...
    def netbios(self, ip: str, timeout_s: float = 1.5) -> NetbiosInfo | None: ...
    def mdns_query(self, ip: str, qname: str, qtype: int = 12, timeout_s: float = 1.2) -> list[DnsRecord]: ...
    def ssdp_search(
        self, target: str | None = None, timeout_s: float = 2.5, st: str = "ssdp:all"
    ) -> list[SsdpEntry]: ...
    def upnp_description(self, ip: str, location: str) -> dict[str, str]: ...
    def http_probe(self, ip: str, port: int, tls: bool, timeout_s: float = 3.0) -> HttpProbe | None: ...
    def tcp_banner(self, ip: str, port: int, timeout_s: float = 2.0) -> bytes | None:
        """``None`` when the connection fails; ``b""`` when the service sends nothing within 1.2 s."""
        ...
