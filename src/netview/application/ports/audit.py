"""Audit port: who did what. The core makes no calls in stage 1; plugins may through ``ctx.audit``."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AuditEntry:
    t_ms: int
    username: str
    ip: str | None
    action: str
    target: str | None
    outcome: Literal["ok", "denied", "failed"]
    detail: str | None


class AuditSink(Protocol):
    def record(self, entry: AuditEntry) -> None: ...


class NullAuditSink:
    def record(self, entry: AuditEntry) -> None:
        return None
