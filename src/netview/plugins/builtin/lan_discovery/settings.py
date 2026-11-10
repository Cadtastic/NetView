"""lan_discovery settings."""

from pydantic import BaseModel, Field


class LanDiscoverySettings(BaseModel):
    ping_timeout_ms: int = Field(default=800, ge=100, le=5000)
    workers: int = Field(default=64, ge=1, le=256)
