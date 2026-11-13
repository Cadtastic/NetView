"""Plugin-owned tables: port samples, MAC locations and the last snapshot."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from netview.sdk import PluginUnitOfWork, StorageSpec

from .analysis import Attachment
from .model import PortCounters, PortRates, Snapshot, snapshot_from_json, snapshot_to_json

BUCKET_MS = 300_000

metadata = sa.MetaData()

_samples = sa.Table(
    "port_samples",
    metadata,
    sa.Column("switch_id", sa.String, primary_key=True),
    sa.Column("if_index", sa.Integer, primary_key=True),
    sa.Column("resolution", sa.String, primary_key=True),
    sa.Column("t_ms", sa.BigInteger, primary_key=True),
    sa.Column("in_octets", sa.BigInteger, nullable=False),
    sa.Column("out_octets", sa.BigInteger, nullable=False),
    sa.Column("in_bps", sa.Float),
    sa.Column("out_bps", sa.Float),
    sa.Column("in_err_ps", sa.Float),
    sa.Column("out_err_ps", sa.Float),
    sa.Column("in_disc_ps", sa.Float),
    sa.Column("out_disc_ps", sa.Float),
    sa.Column("util_percent", sa.Float),
)

_macs = sa.Table(
    "mac_locations",
    metadata,
    sa.Column("switch_id", sa.String, primary_key=True),
    sa.Column("mac", sa.String, primary_key=True),
    sa.Column("vlan", sa.Integer, primary_key=True),
    sa.Column("if_index", sa.Integer, primary_key=True),
    sa.Column("first_ms", sa.BigInteger, nullable=False),
    sa.Column("last_ms", sa.BigInteger, nullable=False),
    sa.Index("ix_mac_locations_mac", "switch_id", "mac"),
)

_snapshots = sa.Table(
    "snapshots",
    metadata,
    sa.Column("switch_id", sa.String, primary_key=True),
    sa.Column("t_ms", sa.BigInteger, nullable=False),
    sa.Column("body", sa.Text, nullable=False),
)

_RATE_COLUMNS = ("in_bps", "out_bps", "in_err_ps", "out_err_ps", "in_disc_ps", "out_disc_ps", "util_percent")
_SAMPLE_KEY = ("switch_id", "if_index", "resolution", "t_ms")


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
            c = counters.get(r.if_index)
            rows.append(
                {
                    "switch_id": self._id,
                    "if_index": r.if_index,
                    "resolution": "raw",
                    "t_ms": r.t_ms,
                    "in_octets": c.in_octets if c else 0,
                    "out_octets": c.out_octets if c else 0,
                    **{name: getattr(r, name) for name in _RATE_COLUMNS},
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
        self, if_index: int, from_ms: int, to_ms: int, resolution: Literal["raw", "5m"]
    ) -> list[PortRates]:
        stmt = (
            sa.select(_samples)
            .where(
                _samples.c.switch_id == self._id,
                _samples.c.if_index == if_index,
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
                row["if_index"],
                row["t_ms"],
                row["in_bps"],
                row["out_bps"],
                row["in_err_ps"],
                row["out_err_ps"],
                row["in_disc_ps"],
                row["out_disc_ps"],
                row["util_percent"],
            )
            for row in rows
        ]

    def rollup_and_prune(self, now_ms: int, raw_keep_ms: int, rollup_keep_ms: int) -> int:
        """Average complete 5-minute buckets of raw rows, then drop expired rows. Idempotent.

        A bucket that already has a rollup row is left alone, so pruning raw rows later can never
        change an existing mean.
        """
        s = _samples
        r = s.alias("r")
        bucket = (s.c.t_ms // BUCKET_MS) * BUCKET_MS
        done = (
            sa.select(sa.literal(1))
            .where(
                r.c.switch_id == s.c.switch_id,
                r.c.if_index == s.c.if_index,
                r.c.resolution == "5m",
                r.c.t_ms == bucket,
            )
            .exists()
        )
        agg = (
            sa.select(
                s.c.switch_id,
                s.c.if_index,
                sa.literal("5m").label("resolution"),
                bucket.label("t_ms"),
                sa.func.max(s.c.in_octets).label("in_octets"),
                sa.func.max(s.c.out_octets).label("out_octets"),
                *(sa.func.avg(s.c[n]).label(n) for n in _RATE_COLUMNS),
            )
            .where(
                s.c.switch_id == self._id,
                s.c.resolution == "raw",
                bucket + BUCKET_MS <= now_ms,
                ~done,
            )
            .group_by(s.c.switch_id, s.c.if_index, bucket)
        )
        columns = [*_SAMPLE_KEY, "in_octets", "out_octets", *_RATE_COLUMNS]
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

    def touch_macs(self, attachments: Sequence[Attachment], t_ms: int) -> None:
        if not attachments:
            return
        rows = [
            {
                "switch_id": self._id,
                "mac": a.mac,
                "vlan": a.vlan,
                "if_index": a.if_index,
                "first_ms": t_ms,
                "last_ms": t_ms,
            }
            for a in attachments
        ]
        with self._uow() as uow:
            stmt = sqlite_insert(_macs)
            stmt = stmt.on_conflict_do_update(
                index_elements=["switch_id", "mac", "vlan", "if_index"],
                set_={"last_ms": stmt.excluded.last_ms},
            )
            uow.session.execute(stmt, rows)
            uow.commit()

    def seen_macs(self) -> frozenset[str]:
        with self._uow() as uow:
            rows = uow.session.execute(sa.select(_macs.c.mac).where(_macs.c.switch_id == self._id).distinct())
            return frozenset(m for (m,) in rows)

    def mac_history(
        self, *, mac: str | None = None, if_index: int | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        stmt = sa.select(_macs).where(_macs.c.switch_id == self._id)
        if mac is not None:
            stmt = stmt.where(_macs.c.mac == mac)
        if if_index is not None:
            stmt = stmt.where(_macs.c.if_index == if_index)
        stmt = stmt.order_by(_macs.c.last_ms.desc(), _macs.c.mac, _macs.c.vlan).limit(limit)
        with self._uow() as uow:
            rows = uow.session.execute(stmt).mappings().all()
        return [{k: row[k] for k in ("mac", "vlan", "if_index", "first_ms", "last_ms")} for row in rows]

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
