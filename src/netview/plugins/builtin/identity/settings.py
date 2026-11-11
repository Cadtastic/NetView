"""identity settings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IdentitySettings(BaseModel):
    recheck_after_s: int = Field(default=1800, ge=300, le=86400)
    """Seconds before the same device is looked up again (LM 1652)."""
    ssdp_timeout_s: float = Field(default=3.0, gt=0, le=30, title="SSDP timeout (s)")
    mdns_timeout_s: float = Field(default=1.0, gt=0, le=30, title="mDNS timeout (s)")
    netbios_timeout_s: float = Field(default=1.0, gt=0, le=30, title="NetBIOS timeout (s)")
    rdns_timeout_s: float = Field(default=1.5, gt=0, le=30, title="Reverse DNS timeout (s)")
    workers: int = Field(default=16, ge=1, le=64)
