"""The permission catalog: core permissions plus each plugin's automatic and declared ones."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from netview.application.plugins.user_permissions import UserPermission
from netview.application.ports.plugin_admin import PluginInfo

AUTOMATIC = ("view", "use", "configure")
ADMIN_ONLY: frozenset[str] = frozenset({"core.install"})
INSTALL_LOCKED_REASON = "Administrator only: installing runs downloaded code"

_ID = re.compile(r"[a-z0-9_.-]+")


@dataclass(frozen=True)
class PermissionInfo:
    id: str
    label: str
    description: str
    dangerous: bool = False
    locked: str | None = None


@dataclass(frozen=True)
class PermissionGroup:
    owner: str
    title: str
    off: bool
    permissions: tuple[PermissionInfo, ...]


CORE_GROUP = PermissionGroup(
    owner="core",
    title="NetView core",
    off=False,
    permissions=(
        PermissionInfo("core.view", "View devices and dashboard", ""),
        PermissionInfo("core.rename", "Rename devices", ""),
        PermissionInfo("core.forget", "Forget devices", ""),
        PermissionInfo("core.watches", "Manage watches", ""),
        PermissionInfo("core.scan", "Run scans and probes", ""),
        PermissionInfo("core.plugins", "Turn plugins on or off", ""),
        PermissionInfo("core.users", "Manage users and roles", ""),
        PermissionInfo("core.system", "Manage sign-in, HTTPS and general settings", ""),
        PermissionInfo("core.install", "Install plugins", "", locked=INSTALL_LOCKED_REASON),
    ),
)


def automatic_ids(info: PluginInfo) -> list[str]:
    ids: list[str] = []
    if "api" in info.capabilities or "web_ui" in info.capabilities:
        ids.append("view")
    if "api" in info.capabilities:
        ids.append("use")
    if info.settings_schema is not None:
        ids.append("configure")
    return ids


def automatic_permissions(info: PluginInfo) -> list[PermissionInfo]:
    labels = {
        "view": f"View {info.name}",
        "use": f"Use {info.name}",
        "configure": f"Change {info.name} settings",
    }
    return [PermissionInfo(f"{info.id}.{a}", labels[a], "") for a in automatic_ids(info)]


def validate_declared(
    plugin_id: str, declared: Sequence[UserPermission], automatic_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for perm in declared:
        if not _ID.fullmatch(perm.id):
            errors.append(f"{plugin_id}: permission id {perm.id!r} must match [a-z0-9_.-]+")
        if perm.id in seen:
            errors.append(f"{plugin_id}: permission id {perm.id!r} is declared twice")
        seen.add(perm.id)
        if perm.id in AUTOMATIC and perm.id not in automatic_ids:
            errors.append(
                f"{plugin_id}: may not declare {perm.id!r}: the plugin has no automatic {perm.id} permission"
            )
    return errors


def plugin_group(info: PluginInfo) -> PermissionGroup:
    perms = automatic_permissions(info)
    index = {p.id: i for i, p in enumerate(perms)}
    for d in info.user_permissions:
        full = f"{info.id}.{d.id}"
        entry = PermissionInfo(full, d.label, d.description, d.dangerous)
        if full in index:
            perms[index[full]] = entry
        else:
            perms.append(entry)
    return PermissionGroup(info.id, info.name, info.state != "active", tuple(perms))


def build_catalog(plugins: Sequence[PluginInfo]) -> list[PermissionGroup]:
    groups = [CORE_GROUP]
    shown = [p for p in plugins if p.state in ("active", "disabled", "failed")]
    for info in sorted(shown, key=lambda p: p.name):
        group = plugin_group(info)
        if group.permissions:
            groups.append(group)
    return groups


def catalog_ids(groups: Iterable[PermissionGroup]) -> set[str]:
    return {p.id for g in groups for p in g.permissions if p.locked is None}


def default_permission_for(plugin_id: str, method: str) -> str:
    suffix = "view" if method.upper() in ("GET", "HEAD", "OPTIONS") else "use"
    return f"{plugin_id}.{suffix}"
