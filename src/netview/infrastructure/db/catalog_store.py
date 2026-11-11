"""SQL cache of the plugin catalog (a single row)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from netview.application.plugins.plugin_json import index_to_dict, parse_index
from netview.application.ports.plugin_catalog import CatalogSnapshot
from netview.domain.errors import ValidationError
from netview.infrastructure.db.models import PluginCatalogCacheRow

_ROW_ID = 1


class SqlCatalogStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def load(self) -> CatalogSnapshot | None:
        with self._sessions() as session:
            row = session.get(PluginCatalogCacheRow, _ROW_ID)
            if row is None:
                return None
            index = None
            if row.payload:
                try:
                    index = parse_index(json.loads(row.payload))
                except (ValueError, ValidationError):
                    index = None  # an unreadable cache is treated as empty
            return CatalogSnapshot(index, row.source, row.fetched_at_ms, row.error)

    def save(self, snapshot: CatalogSnapshot) -> None:
        payload = json.dumps(index_to_dict(snapshot.index)) if snapshot.index else None
        with self._sessions() as session:
            row = session.get(PluginCatalogCacheRow, _ROW_ID)
            if row is None:
                row = PluginCatalogCacheRow(id=_ROW_ID, source=snapshot.source)
                session.add(row)
            row.source = snapshot.source
            row.fetched_at_ms = snapshot.fetched_at_ms
            row.payload = payload
            row.error = snapshot.error
            session.commit()
