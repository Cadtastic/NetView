"""Inspection settings."""

from pydantic import BaseModel, Field


class InspectionSettings(BaseModel):
    workers: int = Field(default=256, ge=16, le=1024)
    """Threads for a port scan; a scan of more than 5000 ports uses 1024 whatever this says."""
    port_timeout_s: float = Field(default=0.8, ge=0.1, le=10)
    full_scan_timeout_s: float = Field(default=0.5, ge=0.1, le=10)
    """Port timeout when more than 5000 ports are scanned."""
    max_analyzed: int = Field(default=64, ge=1, le=256)
    """Open ports to read banners and web pages from (the rest are listed only)."""
