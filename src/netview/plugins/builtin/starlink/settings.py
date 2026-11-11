"""Starlink router settings."""

from __future__ import annotations

from ipaddress import AddressValueError, IPv4Address

from pydantic import BaseModel, Field, field_validator


class StarlinkSettings(BaseModel):
    router: str | None = None
    """The router's IPv4 address; empty means the gateway."""
    port: int = Field(default=9001, ge=1, le=65535)
    timeout_s: float = Field(default=4.0, ge=1, le=30)

    @field_validator("router")
    @classmethod
    def _check_router(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return str(IPv4Address(value.strip()))
        except (AddressValueError, ValueError) as exc:
            raise ValueError(f"{value!r} is not an IPv4 address") from exc
