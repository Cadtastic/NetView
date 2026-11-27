"""GeoTrace's own tables: saved targets, their traces, and each trace's hops."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from netview.sdk import PluginUnitOfWork, StorageSpec

from .model import Hop, Target, Trace

metadata = sa.MetaData()

_target = sa.Table(
    "geotrace_target",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("address", sa.String, nullable=False),
    sa.Column("family", sa.String, nullable=False),
    sa.Column("interval_min", sa.Integer, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("created_ms", sa.BigInteger, nullable=False),
    sa.Column("updated_ms", sa.BigInteger, nullable=False),
    sqlite_autoincrement=True,
)

_trace = sa.Table(
    "geotrace_trace",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("target_id", sa.Integer, sa.ForeignKey("geotrace_target.id"), nullable=True),
    sa.Column("trigger", sa.String, nullable=False),
    sa.Column("mode", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("error", sa.String, nullable=True),
    sa.Column("started_ms", sa.BigInteger, nullable=False),
    sa.Column("finished_ms", sa.BigInteger, nullable=True),
    sa.Column("resolved_ip", sa.String, nullable=True),
    sa.Column("family", sa.String, nullable=False),
    sa.Column("reached", sa.Boolean, nullable=False),
    sa.Column("hop_count", sa.Integer, nullable=False),
    sa.Column("rtt_ms", sa.Float, nullable=True),
    sa.Column("loss_pct", sa.Float, nullable=True),
    sa.Column("jitter_ms", sa.Float, nullable=True),
    sa.Column("ping_min_ms", sa.Float, nullable=True),
    sa.Column("ping_max_ms", sa.Float, nullable=True),
    sa.Column("signature", sa.String, nullable=False),
    sa.Index("ix_geotrace_trace_target_started", "target_id", "started_ms"),
    sqlite_autoincrement=True,
)

_hop = sa.Table(
    "geotrace_hop",
    metadata,
    sa.Column("trace_id", sa.Integer, sa.ForeignKey("geotrace_trace.id"), primary_key=True),
    sa.Column("n", sa.Integer, primary_key=True),
    sa.Column("ip", sa.String, nullable=True),
    sa.Column("rtts_ms", sa.String, nullable=False),
    sa.Column("city", sa.String, nullable=False),
    sa.Column("region", sa.String, nullable=False),
    sa.Column("country", sa.String, nullable=False),
    sa.Column("lat", sa.Float, nullable=True),
    sa.Column("lon", sa.Float, nullable=True),
    sa.Column("asn", sa.Integer, nullable=True),
    sa.Column("as_org", sa.String, nullable=False),
    sa.Column("placement", sa.String, nullable=False),
    sa.Column("plausible", sa.Boolean, nullable=False),
)

_TARGET_FIELDS = ("name", "address", "family", "interval_min", "enabled", "created_ms", "updated_ms")
_TRACE_FIELDS = tuple(c.name for c in _trace.columns if c.name != "id")
_HOP_FIELDS = (
    "n",
    "ip",
    "city",
    "region",
    "country",
    "lat",
    "lon",
    "asn",
    "as_org",
    "placement",
    "plausible",
)


def storage_spec() -> StorageSpec:
    return StorageSpec(metadata, Path(__file__).parent / "migrations" / "versions")


def _to_target(row: Any) -> Target:
    return Target(row["id"], **{name: row[name] for name in _TARGET_FIELDS})


def _to_hop(row: Any) -> Hop:
    return Hop(**{name: row[name] for name in _HOP_FIELDS}, rtts_ms=tuple(json.loads(row["rtts_ms"])))


def _to_trace(row: Any, hops: tuple[Hop, ...]) -> Trace:
    return Trace(row["id"], **{name: row[name] for name in _TRACE_FIELDS}, hops=hops)


class TargetStore:
    def __init__(self, uow_factory: Callable[[], PluginUnitOfWork]) -> None:
        self._uow = uow_factory

    def list(self) -> list[Target]:
        with self._uow() as uow:
            rows = uow.session.execute(sa.select(_target).order_by(_target.c.id)).mappings().all()
        return [_to_target(r) for r in rows]

    def get(self, id: int) -> Target | None:
        with self._uow() as uow:
            row = uow.session.execute(sa.select(_target).where(_target.c.id == id)).mappings().first()
        return _to_target(row) if row else None

    def add(
        self, name: str, address: str, family: str, interval_min: int, enabled: bool, now_ms: int
    ) -> Target:
        values: dict[str, Any] = {
            "name": name,
            "address": address,
            "family": family,
            "interval_min": interval_min,
            "enabled": enabled,
            "created_ms": now_ms,
            "updated_ms": now_ms,
        }
        with self._uow() as uow:
            new_id = uow.session.execute(sa.insert(_target).values(**values)).inserted_primary_key[0]
            uow.commit()
        return Target(int(new_id), **values)

    def update(self, id: int, **fields: Any) -> Target | None:
        unknown = set(fields) - set(_TARGET_FIELDS)
        if unknown:
            raise ValueError(f"unknown target fields: {sorted(unknown)}")
        with self._uow() as uow:
            if fields:
                uow.session.execute(sa.update(_target).where(_target.c.id == id).values(**fields))
                uow.commit()
            row = uow.session.execute(sa.select(_target).where(_target.c.id == id)).mappings().first()
        return _to_target(row) if row else None

    def delete(self, id: int) -> bool:
        with self._uow() as uow:
            trace_ids = sa.select(_trace.c.id).where(_trace.c.target_id == id)
            uow.session.execute(sa.delete(_hop).where(_hop.c.trace_id.in_(trace_ids)))
            uow.session.execute(sa.delete(_trace).where(_trace.c.target_id == id))
            result = uow.session.execute(sa.delete(_target).where(_target.c.id == id))
            uow.commit()
        return bool(result.rowcount)

    def count(self) -> int:
        with self._uow() as uow:
            return int(uow.session.execute(sa.select(sa.func.count()).select_from(_target)).scalar_one())


class TraceStore:
    def __init__(self, uow_factory: Callable[[], PluginUnitOfWork]) -> None:
        self._uow = uow_factory

    def save(self, trace: Trace) -> int:
        values = {name: getattr(trace, name) for name in _TRACE_FIELDS}
        with self._uow() as uow:
            trace_id = int(uow.session.execute(sa.insert(_trace).values(**values)).inserted_primary_key[0])
            if trace.hops:
                rows = [
                    {
                        **{name: getattr(h, name) for name in _HOP_FIELDS},
                        "trace_id": trace_id,
                        "rtts_ms": json.dumps(list(h.rtts_ms)),
                    }
                    for h in trace.hops
                ]
                uow.session.execute(sa.insert(_hop), rows)
            uow.commit()
        return trace_id

    def get(self, id: int) -> Trace | None:
        with self._uow() as uow:
            row = uow.session.execute(sa.select(_trace).where(_trace.c.id == id)).mappings().first()
            if row is None:
                return None
            return _to_trace(row, self._hops(uow, [id]).get(id, ()))

    def latest(self, target_id: int, n: int = 1, status: str | None = "done") -> list[Trace]:
        query = sa.select(_trace).where(_trace.c.target_id == target_id)
        if status is not None:
            query = query.where(_trace.c.status == status)
        query = query.order_by(_trace.c.started_ms.desc(), _trace.c.id.desc()).limit(n)
        with self._uow() as uow:
            rows = uow.session.execute(query).mappings().all()
            hops = self._hops(uow, [r["id"] for r in rows])
            return [_to_trace(r, hops.get(r["id"], ())) for r in rows]

    def newest(self) -> Trace | None:
        """The newest saved trace of any kind (target or one-off, any status), without hops.

        Ordered by id, which grows with every save (ids are never reused), so it needs no sort."""
        query = sa.select(_trace).order_by(_trace.c.id.desc()).limit(1)
        found = self._without_hops(query)
        return found[0] if found else None

    def other_route(self, target_id: int, signature: str | None, exclude_id: int) -> Trace | None:
        """The newest done trace of a target with a non-empty signature, with its hops.

        With ``signature``, only one whose signature differs from it (the last time the route was
        different). Without, the previous route of any kind. ``exclude_id`` is left out. A trace with an
        empty signature (all hops silent or private) never counts as a route."""
        query = sa.select(_trace).where(
            _trace.c.target_id == target_id,
            _trace.c.status == "done",
            _trace.c.id != exclude_id,
            _trace.c.signature.is_not(None),
            _trace.c.signature.not_in(["", "[]"]),
        )
        if signature is not None:
            query = query.where(_trace.c.signature != signature)
        query = query.order_by(_trace.c.started_ms.desc(), _trace.c.id.desc()).limit(1)
        with self._uow() as uow:
            rows = uow.session.execute(query).mappings().all()
            hops = self._hops(uow, [r["id"] for r in rows])
            found = [_to_trace(r, hops.get(r["id"], ())) for r in rows]
        return found[0] if found else None

    def route_age(self, target_id: int) -> tuple[int, int, bool] | None:
        """``(since_ms, newest_ms, changed)`` for a target's current route, or None if it has none.

        Looks at done traces that reached the target and have a non-empty signature. ``newest_ms`` is the
        newest such trace; ``since_ms`` is the start of the unbroken run of traces with its signature;
        ``changed`` is True when an earlier trace had a different signature (False: steady as far back as
        the saved traces go).
        """
        good = sa.and_(
            _trace.c.target_id == target_id,
            _trace.c.status == "done",
            _trace.c.reached.is_(True),
            _trace.c.signature != "[]",
        )
        with self._uow() as uow:
            newest = (
                uow.session.execute(
                    sa.select(_trace.c.started_ms, _trace.c.signature)
                    .where(good)
                    .order_by(_trace.c.started_ms.desc(), _trace.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if newest is None:
                return None
            other = uow.session.execute(
                sa.select(sa.func.max(_trace.c.started_ms)).where(
                    good, _trace.c.signature != newest["signature"]
                )
            ).scalar_one()
            same = sa.select(sa.func.min(_trace.c.started_ms)).where(
                good, _trace.c.signature == newest["signature"]
            )
            if other is not None:
                same = same.where(_trace.c.started_ms > other)
            since = uow.session.execute(same).scalar_one()
        return int(since), int(newest["started_ms"]), other is not None

    def page(self, target_id: int, before_ms: int | None, limit: int) -> list[Trace]:
        query = sa.select(_trace).where(_trace.c.target_id == target_id)
        if before_ms is not None:
            query = query.where(_trace.c.started_ms < before_ms)
        query = query.order_by(_trace.c.started_ms.desc(), _trace.c.id.desc()).limit(limit)
        return self._without_hops(query)

    def between(self, target_id: int, since_ms: int, until_ms: int) -> list[Trace]:
        query = (
            sa.select(_trace)
            .where(
                _trace.c.target_id == target_id,
                _trace.c.started_ms >= since_ms,
                _trace.c.started_ms <= until_ms,
            )
            .order_by(_trace.c.started_ms, _trace.c.id)
        )
        return self._without_hops(query)

    def delete_older(self, target_cutoff_ms: int, once_cutoff_ms: int) -> int:
        old = sa.or_(
            sa.and_(_trace.c.target_id.is_not(None), _trace.c.started_ms < target_cutoff_ms),
            sa.and_(_trace.c.target_id.is_(None), _trace.c.started_ms < once_cutoff_ms),
        )
        with self._uow() as uow:
            old_ids = sa.select(_trace.c.id).where(old)
            uow.session.execute(sa.delete(_hop).where(_hop.c.trace_id.in_(old_ids)))
            result = uow.session.execute(sa.delete(_trace).where(old))
            uow.commit()
        return int(result.rowcount)

    def _without_hops(self, query: sa.Select[Any]) -> list[Trace]:
        with self._uow() as uow:
            rows = uow.session.execute(query).mappings().all()
        return [_to_trace(r, ()) for r in rows]

    @staticmethod
    def _hops(uow: PluginUnitOfWork, trace_ids: list[int]) -> dict[int, tuple[Hop, ...]]:
        if not trace_ids:
            return {}
        query = sa.select(_hop).where(_hop.c.trace_id.in_(trace_ids)).order_by(_hop.c.trace_id, _hop.c.n)
        out: dict[int, list[Hop]] = {}
        for r in uow.session.execute(query).mappings().all():
            out.setdefault(r["trace_id"], []).append(_to_hop(r))
        return {k: tuple(v) for k, v in out.items()}
