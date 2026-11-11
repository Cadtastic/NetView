"""Plugin-owned tables: port samples and the last snapshot."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from netview.sdk import PluginUnitOfWork, StorageSpec

from .model import PortCounters, PortRates, Snapshot, snapshot_from_json, snapshot_to_json

BUCKET_MS = 300_000

metadata = sa.MetaData()

_samples = sa.Table(
    "gs105e_port_samples",
    metadata,
    sa.Column("switch_id", sa.String, primary_key=True),
    sa.Column("port", sa.Integer, primary_key=True),
    sa.Column("resolution", sa.String, primary_key=True),
    sa.Column("t_ms", sa.BigInteger, primary_key=True),
    sa.Column("rx_bytes", sa.BigInteger, nullable=False),
    sa.Column("tx_bytes", sa.BigInteger, nullable=False),
    sa.Column("crc_errors", sa.BigInteger, nullable=False),
    sa.Column("in_bps", sa.Float),
    sa.Column("out_bps", sa.Float),
    sa.Column("crc_delta", sa.Integer),
    sa.Column("util_percent", sa.Float),
)

_snapshots = sa.Table(
    "gs105e_snapshots",
    metadata,
    sa.Column("switch_id", sa.String, primary_key=True),
    sa.Column("t_ms", sa.BigInteger, nullable=False),
    sa.Column("body", sa.Text, nullable=False),
)

_AVG_COLUMNS = ("in_bps", "out_bps", "util_percent")
_SAMPLE_KEY = ("switch_id", "port", "resolution", "t_ms")


def storage_spec() -> StorageSpec:
    return StorageSpec(metadata, Path(__file__).parent / "migrations" / "versions")


class SwitchStore:
    def __init__(self, uow_factory: Callable[[], PluginUnitOfWork], switch_id: str) -> None:
        self._uow = uow_factory
        self._id = switch_id

    def add_samples(self, rates: Sequence[PortRates], counters: Mapping[int, PortCounters]) -> None:
        if not rates:
            return
        rows = []
        for r in rates:
            c = counters.get(r.port)
            rows.append(
                {
                    "switch_id": self._id,
                    "port": r.port,
                    "resolution": "raw",
                    "t_ms": r.t_ms,
                    "rx_bytes": c.rx_bytes if c else 0,
                    "tx_bytes": c.tx_bytes if c else 0,
                    "crc_errors": c.crc_errors if c else 0,
                    "in_bps": r.in_bps,
                    "out_bps": r.out_bps,
                    "crc_delta": r.crc_delta,
                    "util_percent": r.util_percent,
                }
            )
        with self._uow() as uow:
            stmt = sqlite_insert(_samples)
            stmt = stmt.on_conflict_do_update(
                index_elements=list(_SAMPLE_KEY),
                set_={k: stmt.excluded[k] for k in rows[0] if k not in _SAMPLE_KEY},
            )
            uow.session.execute(stmt, rows)
            uow.commit()

    def samples(
        self, port: int, from_ms: int, to_ms: int, resolution: Literal["raw", "5m"]
    ) -> list[PortRates]:
        stmt = (
            sa.select(_samples)
            .where(
                _samples.c.switch_id == self._id,
                _samples.c.port == port,
                _samples.c.resolution == resolution,
                _samples.c.t_ms >= from_ms,
                _samples.c.t_ms <= to_ms,
            )
            .order_by(_samples.c.t_ms)
        )
        with self._uow() as uow:
            rows = uow.session.execute(stmt).mappings().all()
        return [
            PortRates(
                row["port"],
                row["t_ms"],
                row["in_bps"],
                row["out_bps"],
                row["crc_delta"],
                row["util_percent"],
            )
            for row in rows
        ]

    def rollup_and_prune(self, now_ms: int, raw_keep_ms: int, rollup_keep_ms: int) -> int:
        """Average complete 5-minute buckets of raw rows, then drop expired rows. Idempotent.

        A bucket that already has a rollup row is left alone, so pruning raw rows later can never
        change an existing mean. CRC errors are summed per bucket, byte counts keep their maximum.
        """
        s = _samples
        r = s.alias("r")
        bucket = (s.c.t_ms // BUCKET_MS) * BUCKET_MS
        done = (
            sa.select(sa.literal(1))
            .where(
                r.c.switch_id == s.c.switch_id,
                r.c.port == s.c.port,
                r.c.resolution == "5m",
                r.c.t_ms == bucket,
            )
            .exists()
        )
        agg = (
            sa.select(
                s.c.switch_id,
                s.c.port,
                sa.literal("5m").label("resolution"),
                bucket.label("t_ms"),
                sa.func.max(s.c.rx_bytes).label("rx_bytes"),
                sa.func.max(s.c.tx_bytes).label("tx_bytes"),
                sa.func.max(s.c.crc_errors).label("crc_errors"),
                *(sa.func.avg(s.c[n]).label(n) for n in _AVG_COLUMNS),
                sa.func.sum(s.c.crc_delta).label("crc_delta"),
            )
            .where(
                s.c.switch_id == self._id,
                s.c.resolution == "raw",
                bucket + BUCKET_MS <= now_ms,
                ~done,
            )
            .group_by(s.c.switch_id, s.c.port, bucket)
        )
        columns = [
            *_SAMPLE_KEY,
            "rx_bytes",
            "tx_bytes",
            "crc_errors",
            *_AVG_COLUMNS,
            "crc_delta",
        ]
        deleted = 0
        with self._uow() as uow:
            uow.session.execute(sa.insert(s).from_select(columns, agg))
            for resolution, keep in (("raw", raw_keep_ms), ("5m", rollup_keep_ms)):
                res = uow.session.execute(
                    sa.delete(s).where(
                        s.c.switch_id == self._id,
                        s.c.resolution == resolution,
                        s.c.t_ms < now_ms - keep,
                    )
                )
                deleted += res.rowcount
            uow.commit()
        return deleted

    def save_snapshot(self, s: Snapshot) -> None:
        values = {"switch_id": self._id, "t_ms": s.t_ms, "body": snapshot_to_json(s)}
        with self._uow() as uow:
            stmt = sqlite_insert(_snapshots)
            stmt = stmt.on_conflict_do_update(
                index_elements=["switch_id"],
                set_={"t_ms": stmt.excluded.t_ms, "body": stmt.excluded.body},
            )
            uow.session.execute(stmt, values)
            uow.commit()

    def load_snapshot(self) -> Snapshot | None:
        with self._uow() as uow:
            body = uow.session.execute(
                sa.select(_snapshots.c.body).where(_snapshots.c.switch_id == self._id)
            ).scalar_one_or_none()
        return None if body is None else snapshot_from_json(body)
