"""Import a lan_monitor ``lan_store.json`` (schema ``ketiv.network-tools/lan-store@1``).

The source file is only ever read. Existing nicknames are never overwritten unless the caller
asks for it with ``prefer_source``.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from netview.application.ports.clock import Clock
from netview.application.ports.uow import UnitOfWork, UnitOfWorkFactory
from netview.domain.device import Device, DeviceStatus
from netview.domain.errors import ValidationError
from netview.domain.naming import NAME_RANKS, NameClaim, TypeClaim
from netview.domain.nickname import MAX_NICKNAME_LEN, NicknameChange
from netview.domain.watch import parse_watch_spec

SCHEMA_PREFIX = "ketiv.network-tools/lan-store@"
_BY_IMPORT = "import: lan_monitor"
_BY_IMPORT_PREFER = "import: lan_monitor (prefer source)"
_TYPE_SOURCE = "lan_monitor"


@dataclass(frozen=True)
class NicknameConflict:
    key: str
    netview: str
    source: str


@dataclass
class ImportReport:
    devices_added: int = 0
    devices_updated: int = 0
    nicknames_added: int = 0
    history_added: int = 0
    watches_added: int = 0
    conflicts: list[NicknameConflict] = field(default_factory=list)


class LanmonImporter:
    def __init__(self, uow: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def run(self, path: Path, prefer_source: bool = False, dry_run: bool = False) -> ImportReport:
        data = _read(path)
        report = ImportReport()
        with self._uow() as uow:
            self._known(uow, _mapping(data.get("known")), report)
            self._labels(uow, _mapping(data.get("labels")), prefer_source, report)
            self._history(uow, data.get("label_history"), report)
            self._watches(uow, data.get("watches"), report)
            if dry_run:
                uow.rollback()
            else:
                uow.commit()
        return report

    def _known(self, uow: UnitOfWork, known: dict[str, Any], report: ImportReport) -> None:
        for key, raw in known.items():
            entry = _mapping(raw)
            first = _int(entry.get("first_seen"))
            last = _int(entry.get("last_seen"))
            device = uow.devices.get(key)
            if device is None:
                mac = entry.get("mac")
                uow.devices.add(
                    Device(
                        key=key,
                        ip=str(entry.get("ip") or ""),
                        mac=str(mac) if mac else None,
                        vendor="",
                        first_seen_ms=first,
                        last_seen_ms=max(first, last),
                        status=DeviceStatus.OFFLINE,
                    )
                )
                report.devices_added += 1
            else:
                widened = False
                if first and (not device.first_seen_ms or first < device.first_seen_ms):
                    device.first_seen_ms = first
                    widened = True
                if last > device.last_seen_ms:
                    device.last_seen_ms = last
                    widened = True
                if widened:
                    uow.devices.save(device)
                    report.devices_updated += 1
            name = entry.get("name")
            if name:
                source = str(entry.get("name_source") or "")
                uow.identity.upsert_claim(NameClaim(key, str(name), source, NAME_RANKS.get(source, 1), 0))
            kind = entry.get("type")
            if kind:
                uow.identity.upsert_type(TypeClaim(key, str(kind), "imported", _TYPE_SOURCE))

    def _labels(
        self, uow: UnitOfWork, labels: dict[str, Any], prefer_source: bool, report: ImportReport
    ) -> None:
        for key, raw in labels.items():
            source = str(raw if raw is not None else "").strip()[:MAX_NICKNAME_LEN].strip()
            if not source:
                continue  # an empty source value never clears anything
            current = uow.nicknames.get(key) or ""
            if current == source:
                continue
            if current and not prefer_source:
                report.conflicts.append(NicknameConflict(key, current, source))
                continue
            by = _BY_IMPORT_PREFER if current else _BY_IMPORT
            uow.nicknames.set(key, source)
            uow.nicknames.add_history(NicknameChange(key, current, source, by, self._clock.now_ms()))
            report.nicknames_added += 1
            report.history_added += 1

    def _history(self, uow: UnitOfWork, entries: Any, report: ImportReport) -> None:
        if not isinstance(entries, list):
            return
        for raw in entries:
            if not isinstance(raw, dict) or not raw.get("key"):
                continue
            change = NicknameChange(
                key=str(raw["key"]),
                old=str(raw.get("old") or ""),
                new=str(raw.get("new") or ""),
                by=str(raw.get("by") or "lan_monitor"),
                t_ms=_int(raw.get("t")),
            )
            if uow.nicknames.has_history(change):
                continue
            uow.nicknames.add_history(change)
            report.history_added += 1

    def _watches(self, uow: UnitOfWork, specs: Any, report: ImportReport) -> None:
        if not isinstance(specs, list):
            return
        existing = {w.ip for w in uow.watches.list()}
        for spec in specs:
            try:
                watch = parse_watch_spec(str(spec))
            except ValidationError:
                continue  # the old monitor skipped bad specs too
            if watch.ip in existing:
                continue
            uow.watches.add(watch)
            existing.add(watch.ip)
            report.watches_added += 1


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path} is not a lan_monitor store")
    schema = data.get("schema")
    if not isinstance(schema, str) or not schema.startswith(SCHEMA_PREFIX):
        raise ValidationError(f"{path} is not a lan_monitor store (schema {schema!r})")
    return data


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
