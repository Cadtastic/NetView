"""Domain events."""

from dataclasses import dataclass
from enum import StrEnum


class EventKind(StrEnum):
    NEW = "new"
    MOVED = "moved"
    ONLINE = "online"
    OFFLINE = "offline"
    CONFLICT = "conflict"
    NAME = "name"
    NICKNAME = "nickname"
    FORGOTTEN = "forgotten"
    TYPE = "type"
    WATCH = "watch"
    PLUGIN = "plugin"


@dataclass(frozen=True)
class DomainEvent:
    kind: EventKind
    text: str
    t_ms: int
    ip: str | None = None
    key: str | None = None
