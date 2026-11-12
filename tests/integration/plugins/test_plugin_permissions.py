from typing import Any

import pytest
from conftest import HostEnv
from sample_plugins.declares import BadIdPlugin, DeclaresPlugin, NoSettingsConfigurePlugin, TwicePlugin
from sample_plugins.sdk14 import Sdk14Plugin

from netview.application.auth.catalog import build_catalog
from netview.application.auth.principal import SYSTEM_PRINCIPAL, Principal, current_principal
from netview.application.plugins.context import PluginIdentity
from netview.application.ports.audit import AuditEntry
from netview.domain.auth import PermissionSet
from netview.infrastructure.plugins.context import DefaultPluginContext
from netview.sdk import UserPermission

DEMO_GUID = "9a8b7c6d-1111-4222-8333-444455556666"


def _ids(host: Any, owner: str) -> list[str]:
    group = next(g for g in build_catalog(host.list()) if g.owner == owner)
    return [p.id for p in group.permissions]


def test_sdk14_plugin_loads_with_automatic_permissions(env: HostEnv) -> None:
    host = env.host([Sdk14Plugin])
    host.load_all()

    guid = Sdk14Plugin.manifest.guid
    assert host.get(env.id(Sdk14Plugin)).state == "active"
    assert host.get(env.id(Sdk14Plugin)).user_permissions == []
    assert _ids(host, guid) == [f"{guid}.view", f"{guid}.use"]


def test_declared_permissions_fill_plugin_info_and_catalog(env: HostEnv) -> None:
    host = env.host([DeclaresPlugin])
    host.load_all()

    guid = DeclaresPlugin.manifest.guid
    assert host.get(env.id(DeclaresPlugin)).user_permissions == [
        UserPermission("console", "Open the console", "Run commands", dangerous=True),
        UserPermission("use", "Send commands"),
    ]
    group = next(g for g in build_catalog(host.list()) if g.owner == guid)
    by_id = {p.id: p for p in group.permissions}
    assert list(by_id) == [f"{guid}.view", f"{guid}.use", f"{guid}.console"]
    assert by_id[f"{guid}.use"].label == "Send commands"  # an automatic permission, relabelled
    assert by_id[f"{guid}.console"].dangerous


@pytest.mark.parametrize(
    ("plugin", "word"),
    [
        (BadIdPlugin, "must match"),
        (TwicePlugin, "twice"),
        (NoSettingsConfigurePlugin, "automatic configure"),
    ],
)
def test_bad_declaration_fails_plugin_load(env: HostEnv, plugin: Any, word: str) -> None:
    host = env.host([plugin])
    host.load_all()

    info = host.get(env.id(plugin))
    assert info.state == "failed"
    assert info.error is not None
    assert word in info.error
    assert info.user_permissions == []
    assert host.routers() == []


def test_disabled_plugin_still_declares_its_permissions(env: HostEnv) -> None:
    guid = DeclaresPlugin.manifest.guid
    host = env.host([DeclaresPlugin], seeds={guid: {"enabled": False}})
    host.load_all()

    assert host.get(env.id(DeclaresPlugin)).state == "disabled"
    group = next(g for g in build_catalog(host.list()) if g.owner == guid)
    assert group.off
    assert f"{guid}.console" in [p.id for p in group.permissions]


def _context(env: HostEnv, sink: Any = None) -> DefaultPluginContext:
    ctx = env.context_factory(PluginIdentity(DEMO_GUID, 5, "Demo", "demo"), None)
    if sink is not None:
        ctx._audit_sink = sink
    return ctx


def test_ctx_principal_is_caller_in_request_and_system_in_job(env: HostEnv) -> None:
    ctx = _context(env)
    caller = Principal(7, "kdoe", "K Doe", "local", PermissionSet(everything=False, ids=frozenset()))

    assert ctx.principal() is SYSTEM_PRINCIPAL  # a job: no request, no caller
    token = current_principal.set(caller)
    try:
        assert ctx.principal() is caller
    finally:
        current_principal.reset(token)
    ctx.close()


class _Recorder:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def test_ctx_audit_hands_the_caller_to_the_sink(env: HostEnv) -> None:
    sink = _Recorder()
    ctx = _context(env, sink)
    caller = Principal(7, "kdoe", "K Doe", "local", PermissionSet(everything=False, ids=frozenset()))
    token = current_principal.set(caller)
    try:
        ctx.audit("console.open", target="sw1", detail="by hand")
        ctx.audit("console.open", ok=False)
    finally:
        current_principal.reset(token)
    ctx.audit("poll")

    assert [(e.username, e.action, e.target, e.outcome, e.detail) for e in sink.entries] == [
        ("kdoe", "console.open", "sw1", "ok", "by hand"),
        ("kdoe", "console.open", None, "failed", None),
        ("system", "poll", None, "ok", None),
    ]
    ctx.close()


def test_ctx_require_prefixes_relative_ids_and_keeps_core_ids(env: HostEnv) -> None:
    ctx = _context(env)

    assert ctx.require("console").dependency.__netview_permission__ == f"{DEMO_GUID}.console"
    assert ctx.require("core.scan").dependency.__netview_permission__ == "core.scan"
    ctx.close()


def test_require_prefixes_guid_not_the_runtime_key(env: HostEnv) -> None:
    ctx = _context(env)

    assert (ctx.guid, ctx.source_id, ctx.display_name) == (DEMO_GUID, 5, "Demo")
    assert ctx.log.name == "netview.plugin.p5"
    assert ctx.require("view").dependency.__netview_permission__ == f"{DEMO_GUID}.view"
    assert ctx.require("view").dependency.__netview_permission__ != "5.view"
    ctx.close()
