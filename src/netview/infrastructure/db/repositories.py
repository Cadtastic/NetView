"""SQL implementations of the repository ports."""

import json

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from netview.application.ports.repositories import PluginState
from netview.domain.device import Device, DeviceStatus
from netview.domain.events import DomainEvent, EventKind
from netview.domain.inspection import InspectionReport, ReportSection
from netview.domain.naming import Hint, NameClaim, TypeClaim
from netview.domain.nickname import NicknameChange
from netview.domain.watch import Watch
from netview.infrastructure.db.models import (
    DeviceRow,
    EventRow,
    HintRow,
    InspectionReportRow,
    NameClaimRow,
    NicknameHistoryRow,
    NicknameRow,
    PluginStateRow,
    TypeClaimRow,
    WatchRow,
)


def _device(r: DeviceRow) -> Device:
    return Device(
        key=r.key,
        ip=r.ip,
        mac=r.mac,
        vendor=r.vendor,
        first_seen_ms=r.first_seen_ms,
        last_seen_ms=r.last_seen_ms,
        status=DeviceStatus(r.status),
        rtt_ms=r.rtt_ms,
        ttl=r.ttl,
        is_self=r.is_self,
        missed=r.missed,
        is_new=r.is_new,
    )


class SqlDeviceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, key: str) -> Device | None:
        row = self._s.get(DeviceRow, key)
        return _device(row) if row else None

    def get_by_ip(self, ip: str) -> Device | None:
        row = self._s.scalars(select(DeviceRow).where(DeviceRow.ip == ip).limit(1)).first()
        return _device(row) if row else None

    def list(self) -> list[Device]:
        rows = self._s.scalars(select(DeviceRow).order_by(DeviceRow.first_seen_ms, DeviceRow.key))
        return [_device(r) for r in rows]

    def add(self, device: Device) -> None:
        self.save(device)

    def save(self, device: Device) -> None:
        self._s.merge(
            DeviceRow(
                key=device.key,
                ip=device.ip,
                mac=device.mac,
                vendor=device.vendor,
                first_seen_ms=device.first_seen_ms,
                last_seen_ms=device.last_seen_ms,
                status=device.status.value,
                rtt_ms=device.rtt_ms,
                ttl=device.ttl,
                is_self=device.is_self,
                missed=device.missed,
                is_new=device.is_new,
            )
        )
        self._s.flush()

    def remove(self, key: str) -> None:
        self._s.execute(delete(DeviceRow).where(DeviceRow.key == key))
        self._s.expire_all()


class SqlIdentityRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _claim(r: NameClaimRow) -> NameClaim:
        return NameClaim(r.key, r.name, r.source, r.rank, r.checked_ms)

    def claims(self, key: str) -> list[NameClaim]:
        rows = self._s.scalars(select(NameClaimRow).where(NameClaimRow.key == key))
        return [self._claim(r) for r in rows]

    def all_claims(self) -> dict[str, list[NameClaim]]:
        out: dict[str, list[NameClaim]] = {}
        for r in self._s.scalars(select(NameClaimRow)):
            out.setdefault(r.key, []).append(self._claim(r))
        return out

    def upsert_claim(self, c: NameClaim) -> None:
        self._s.merge(
            NameClaimRow(key=c.key, source=c.source, name=c.name, rank=c.rank, checked_ms=c.checked_ms)
        )
        self._s.flush()

    def types(self, key: str) -> list[TypeClaim]:
        rows = self._s.scalars(select(TypeClaimRow).where(TypeClaimRow.key == key))
        return [TypeClaim(r.key, r.type, r.reason, r.source) for r in rows]

    def upsert_type(self, t: TypeClaim) -> None:
        self._s.merge(TypeClaimRow(key=t.key, source=t.source, type=t.type, reason=t.reason))
        self._s.flush()

    def hints(self, key: str) -> list[Hint]:
        rows = self._s.scalars(select(HintRow).where(HintRow.key == key).order_by(HintRow.id))
        return [Hint(r.key, r.text, r.source) for r in rows]

    def replace_hints(self, key: str, source: str, hints: list[Hint]) -> None:
        self._s.execute(delete(HintRow).where(HintRow.key == key, HintRow.source == source))
        for h in hints:
            self._s.add(HintRow(key=key, source=source, text=h.text))
        self._s.flush()

    def rekey(self, old: str, new: str) -> None:
        """Move all rows from ``old`` to ``new``; same-source rows already on ``new`` are replaced."""
        if old == new:
            return
        self._s.flush()
        for model in (NameClaimRow, TypeClaimRow, HintRow):
            sources = list(self._s.scalars(select(model.source).where(model.key == old)))
            if sources:
                self._s.execute(delete(model).where(model.key == new, model.source.in_(sources)))
            self._s.execute(update(model).where(model.key == old).values(key=new))
        self._s.expire_all()


class SqlNicknameRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, key: str) -> str | None:
        row = self._s.get(NicknameRow, key)
        return row.value if row else None

    def all(self) -> dict[str, str]:
        return {r.key: r.value for r in self._s.scalars(select(NicknameRow))}

    def set(self, key: str, value: str | None) -> None:
        if value:
            self._s.merge(NicknameRow(key=key, value=value))
        else:
            row = self._s.get(NicknameRow, key)
            if row is not None:
                self._s.delete(row)
        self._s.flush()

    def add_history(self, c: NicknameChange) -> None:
        self._s.add(NicknameHistoryRow(key=c.key, old=c.old, new=c.new, by=c.by, t_ms=c.t_ms))
        self._s.flush()

    def history(self, key: str | None = None, limit: int = 500) -> list[NicknameChange]:
        q = select(NicknameHistoryRow)
        if key is not None:
            q = q.where(NicknameHistoryRow.key == key)
        q = q.order_by(NicknameHistoryRow.t_ms.desc(), NicknameHistoryRow.id.desc()).limit(limit)
        return [NicknameChange(r.key, r.old, r.new, r.by, r.t_ms) for r in self._s.scalars(q)]

    def has_history(self, c: NicknameChange) -> bool:
        q = (
            select(NicknameHistoryRow.id)
            .where(
                NicknameHistoryRow.key == c.key,
                NicknameHistoryRow.old == c.old,
                NicknameHistoryRow.new == c.new,
                NicknameHistoryRow.by == c.by,
                NicknameHistoryRow.t_ms == c.t_ms,
            )
            .limit(1)
        )
        return self._s.scalars(q).first() is not None

    def rekey(self, old: str, new: str) -> None:
        """Move the nickname (an existing one on ``new`` wins) and the history."""
        if old == new:
            return
        self._s.flush()
        row = self._s.get(NicknameRow, old)
        if row is not None:
            value = row.value
            self._s.delete(row)
            self._s.flush()
            if self._s.get(NicknameRow, new) is None:
                self._s.add(NicknameRow(key=new, value=value))
        self._s.execute(update(NicknameHistoryRow).where(NicknameHistoryRow.key == old).values(key=new))
        self._s.flush()
        self._s.expire_all()


class SqlWatchRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def list(self) -> list[Watch]:
        rows = self._s.scalars(select(WatchRow).order_by(WatchRow.ip))
        return [Watch(r.ip, tuple(int(p) for p in r.ports.split(",") if p), r.label) for r in rows]

    def add(self, w: Watch) -> None:
        self._s.merge(WatchRow(ip=w.ip, ports=",".join(str(p) for p in w.ports), label=w.label))
        self._s.flush()

    def remove(self, ip: str) -> bool:
        row = self._s.get(WatchRow, ip)
        if row is None:
            return False
        self._s.delete(row)
        self._s.flush()
        return True


class SqlEventRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, e: DomainEvent) -> None:
        self._s.add(EventRow(t_ms=e.t_ms, kind=e.kind.value, text=e.text, ip=e.ip, key=e.key))
        self._s.flush()

    def recent(self, limit: int = 300) -> list[DomainEvent]:
        q = select(EventRow).order_by(EventRow.id.desc()).limit(limit)
        return [DomainEvent(EventKind(r.kind), r.text, r.t_ms, r.ip, r.key) for r in self._s.scalars(q)]


class SqlInspectionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, r: InspectionReport) -> None:
        sections = [
            {"plugin_id": s.plugin_id, "id": s.id, "title": s.title, "data": dict(s.data), "error": s.error}
            for s in r.sections
        ]
        self._s.add(
            InspectionReportRow(
                ip=r.ip,
                ports_spec=r.ports_spec,
                started_ms=r.started_ms,
                finished_ms=r.finished_ms,
                sections_json=json.dumps(sections),
            )
        )
        self._s.flush()

    def latest(self, ip: str) -> InspectionReport | None:
        q = select(InspectionReportRow).where(InspectionReportRow.ip == ip)
        row = self._s.scalars(q.order_by(InspectionReportRow.id.desc()).limit(1)).first()
        if row is None:
            return None
        sections = [
            ReportSection(s["plugin_id"], s["id"], s["title"], s["data"], s.get("error"))
            for s in json.loads(row.sections_json)
        ]
        return InspectionReport(row.ip, row.ports_spec, row.started_ms, row.finished_ms, sections)


class SqlPluginStateRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, plugin_id: str) -> PluginState | None:
        row = self._s.get(PluginStateRow, plugin_id)
        if row is None:
            return None
        return PluginState(row.plugin_id, row.enabled, json.loads(row.settings_json), row.installed_version)

    def save(self, s: PluginState) -> None:
        self._s.merge(
            PluginStateRow(
                plugin_id=s.plugin_id,
                enabled=s.enabled,
                settings_json=json.dumps(s.settings),
                installed_version=s.installed_version,
            )
        )
        self._s.flush()
