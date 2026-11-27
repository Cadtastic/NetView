"""GeoTrace's own tables. None yet: later tasks add geotrace_target, geotrace_trace and geotrace_hop."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from netview.sdk import StorageSpec

metadata = sa.MetaData()


def storage_spec() -> StorageSpec:
    return StorageSpec(metadata, Path(__file__).parent / "migrations" / "versions")
