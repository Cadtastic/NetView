"""Plugin-owned table: the saved TV list, in display order."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa

from netview.sdk import PluginUnitOfWork, StorageSpec

from .model import FIELDS, SavedTv

metadata = sa.MetaData()

_tvs = sa.Table(
    "roku_tvs",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("serial", sa.String, nullable=False),
    sa.Column("ip", sa.String, nullable=False),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("label", sa.String, nullable=False),
    sa.Column("model", sa.String, nullable=False),
    sa.Column("location", sa.String, nullable=False),
    sa.Column("tv", sa.Boolean, nullable=False),
    sa.Column("found_by", sa.String, nullable=False),
    sa.Column("first_seen", sa.String, nullable=False),
    sa.Column("last_seen", sa.String, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
)


def storage_spec() -> StorageSpec:
    return StorageSpec(metadata, Path(__file__).parent / "migrations" / "versions")


class TvStore:
    def __init__(self, uow_factory: Callable[[], PluginUnitOfWork]) -> None:
        self._uow = uow_factory

    def load(self) -> list[SavedTv]:
        with self._uow() as uow:
            rows = uow.session.execute(sa.select(_tvs).order_by(_tvs.c.position)).mappings().all()
        return [SavedTv(**{name: row[name] for name in FIELDS}) for row in rows]

    def replace(self, tvs: list[SavedTv]) -> None:
        rows = [{**{name: getattr(tv, name) for name in FIELDS}, "position": i} for i, tv in enumerate(tvs)]
        with self._uow() as uow:
            uow.session.execute(sa.delete(_tvs))
            if rows:
                uow.session.execute(sa.insert(_tvs), rows)
            uow.commit()
