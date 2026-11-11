"""The saved Roku TV list's value types."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass
class SavedTv:
    id: str
    serial: str
    ip: str
    name: str
    label: str
    model: str
    location: str
    tv: bool
    found_by: str
    first_seen: str
    last_seen: str

    @property
    def title(self) -> str:
        return self.label or self.name or self.ip


@dataclass(frozen=True)
class ScanHit:
    ip: str
    serial: str
    name: str
    model: str
    location: str
    tv: bool
    found_by: str


FIELDS: tuple[str, ...] = tuple(f.name for f in fields(SavedTv))
