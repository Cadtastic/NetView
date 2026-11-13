"""The plugin's own table: the last counters seen per client, so a restart can start with a rate."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = sa.MetaData()

counters = sa.Table(
    "counters",
    metadata,
    sa.Column("ip", sa.String, primary_key=True),
    sa.Column("name", sa.String, nullable=False, server_default=""),
    sa.Column("down_bytes", sa.BigInteger, nullable=False),
    sa.Column("up_bytes", sa.BigInteger, nullable=False),
    sa.Column("t_ms", sa.BigInteger, nullable=False),
)

KEEP_MS = 86_400_000  # a client not seen for a day is forgotten


@dataclass(frozen=True)
class StoredCounter:
    ip: str
    name: str
    down_bytes: int
    up_bytes: int
    t_ms: int


def load(session: Any) -> dict[str, StoredCounter]:
    rows = session.execute(sa.select(counters)).all()
    return {r.ip: StoredCounter(r.ip, r.name, r.down_bytes, r.up_bytes, r.t_ms) for r in rows}


def save(session: Any, rows: Iterable[StoredCounter], now_ms: int) -> None:
    """Upsert every row, then drop the ones older than a day."""
    values = [
        {"ip": r.ip, "name": r.name, "down_bytes": r.down_bytes, "up_bytes": r.up_bytes, "t_ms": r.t_ms}
        for r in rows
    ]
    if values:
        stmt = sqlite_insert(counters)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[counters.c.ip],
                set_={c: getattr(stmt.excluded, c) for c in ("name", "down_bytes", "up_bytes", "t_ms")},
            ),
            values,
        )
    session.execute(sa.delete(counters).where(counters.c.t_ms < now_ms - KEEP_MS))
