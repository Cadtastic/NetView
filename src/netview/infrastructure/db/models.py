"""Core tables (SQLAlchemy declarative mapping)."""

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CoreBase(DeclarativeBase):
    pass


class DeviceRow(CoreBase):
    __tablename__ = "devices"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    ip: Mapped[str] = mapped_column(String, index=True)
    mac: Mapped[str | None] = mapped_column(String, nullable=True)
    vendor: Mapped[str] = mapped_column(String, default="")
    first_seen_ms: Mapped[int] = mapped_column(Integer)
    last_seen_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    rtt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_self: Mapped[bool] = mapped_column(Boolean, default=False)
    missed: Mapped[int] = mapped_column(Integer, default=0)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)


class NameClaimRow(CoreBase):
    __tablename__ = "name_claims"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    rank: Mapped[float] = mapped_column(Float)
    checked_ms: Mapped[int] = mapped_column(Integer)


class TypeClaimRow(CoreBase):
    __tablename__ = "type_claims"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, default="")
    updated_ms: Mapped[int] = mapped_column(Integer, default=0)


class HintRow(CoreBase):
    __tablename__ = "hints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)


class NicknameRow(CoreBase):
    __tablename__ = "nicknames"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


class NicknameHistoryRow(CoreBase):
    __tablename__ = "nickname_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, index=True)
    old: Mapped[str] = mapped_column(String)
    new: Mapped[str] = mapped_column(String)
    by: Mapped[str] = mapped_column(String)
    t_ms: Mapped[int] = mapped_column(Integer)


class WatchRow(CoreBase):
    __tablename__ = "watches"

    ip: Mapped[str] = mapped_column(String, primary_key=True)
    ports: Mapped[str] = mapped_column(String, default="")
    label: Mapped[str] = mapped_column(String, default="")


class EventRow(CoreBase):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    t_ms: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    key: Mapped[str | None] = mapped_column(String, nullable=True)


class InspectionReportRow(CoreBase):
    __tablename__ = "inspection_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String, index=True)
    ports_spec: Mapped[str] = mapped_column(String, default="")
    started_ms: Mapped[int] = mapped_column(Integer)
    finished_ms: Mapped[int] = mapped_column(Integer)
    sections_json: Mapped[str] = mapped_column(Text)


class PluginStateRow(CoreBase):
    __tablename__ = "plugin_state"

    plugin_id: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    installed_version: Mapped[str | None] = mapped_column(String, nullable=True)
