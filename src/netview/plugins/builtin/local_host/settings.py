"""local_host settings."""

from pydantic import BaseModel, Field


class LocalHostSettings(BaseModel):
    throughput_interval_s: float = Field(default=5.0, ge=1, le=60)
    connections_interval_s: float = Field(default=10.0, ge=5, le=120)
