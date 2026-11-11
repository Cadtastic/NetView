"""health settings."""

from __future__ import annotations

from ipaddress import AddressValueError, IPv4Address

from pydantic import BaseModel, Field, field_validator


def _ipv4(value: str) -> str:
    try:
        return str(IPv4Address(value.strip()))
    except (AddressValueError, ValueError) as exc:
        raise ValueError(f"{value!r} is not an IPv4 address") from exc


class HealthSettings(BaseModel):
    internet_target: str = Field(default="1.1.1.1", title="Internet ping target")
    dns_servers: list[str] = Field(
        default_factory=list,
        max_length=2,
        title="DNS servers",
        description="Up to two, one per line. Empty means the gateway and 1.1.1.1.",
    )
    """Empty means the gateway and 1.1.1.1."""
    dns_names: list[str] = Field(
        default_factory=lambda: [
            "www.google.com",
            "www.cloudflare.com",
            "www.microsoft.com",
            "www.amazon.com",
        ],
        min_length=1,
        title="DNS test names",
        description="Names to look up, one per line; one is picked at random each time.",
    )
    ping_timeout_ms: int = Field(default=1000, ge=100, le=5000)
    internet_timeout_ms: int = Field(default=1500, ge=100, le=5000)
    port_timeout_s: float = Field(default=1.5, ge=0.2, le=10)
    max_devices: int = Field(default=64, ge=0, le=64, title="Devices pinged at most")

    @field_validator("internet_target")
    @classmethod
    def _check_target(cls, value: str) -> str:
        return _ipv4(value)

    @field_validator("dns_servers")
    @classmethod
    def _check_servers(cls, value: list[str]) -> list[str]:
        return [_ipv4(v) for v in value]
