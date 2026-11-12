"""Core tables (SQLAlchemy declarative mapping)."""

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, text
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
    __table_args__ = (Index("ix_inspection_reports_ip_id", "ip", "id"),)  # migration 0002

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


class PluginCatalogCacheRow(CoreBase):
    __tablename__ = "plugin_catalog_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1: one cached catalog
    source: Mapped[str] = mapped_column(String)
    fetched_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserRow(CoreBase):
    __tablename__ = "users"
    __table_args__ = (
        # Backstop for first-run setup on any database: at most one built-in user.
        Index(
            "uq_users_one_builtin",
            "builtin",
            unique=True,
            sqlite_where=text("builtin = 1"),
            postgresql_where=text("builtin = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String, default="local")
    created_ms: Mapped[int] = mapped_column(BigInteger)
    last_sign_in_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    security_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class UserLoginRow(CoreBase):
    __tablename__ = "user_logins"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class RoleRow(CoreBase):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class RolePermissionRow(CoreBase):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(String, primary_key=True)


class UserRoleRow(CoreBase):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class SessionRow(CoreBase):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_ms: Mapped[int] = mapped_column(BigInteger)
    last_seen_ms: Mapped[int] = mapped_column(BigInteger)
    ip: Mapped[str] = mapped_column(String, default="")
    user_agent: Mapped[str] = mapped_column(String, default="")
    security_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AppSettingRow(CoreBase):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
