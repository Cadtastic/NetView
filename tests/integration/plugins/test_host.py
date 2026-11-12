import logging
from pathlib import Path
from typing import Any

import pytest
from conftest import HostEnv
from sample_plugins.bad_sdk import BadSdkPlugin
from sample_plugins.crash_setup import CrashSetupPlugin
from sample_plugins.declares import DeclaresPlugin
from sample_plugins.good import GoodPlugin
from sample_plugins.nested_secret import NestedSecretPlugin
from sample_plugins.secretive import SecretivePlugin
from sample_plugins.undeclared import UndeclaredPlugin
from sqlalchemy import inspect

from netview.application.capabilities import Capability
from netview.domain.errors import NotFoundError, ValidationError
from netview.infrastructure.db.engine import make_plugin_engine, plugin_data_file
from netview.infrastructure.plugins.discovery import DiscoveredPlugin
from netview.presentation.api.schemas import PluginOut
from netview.sdk.testing.contract import check_plugin

GOOD_GUID = GoodPlugin.manifest.guid


def test_good_plugin_active_and_registered(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()

    gid = env.id(GoodPlugin)
    info = host.get(gid)
    assert info.state == "active"
    assert info.error is None
    assert info.settings == {"level": 1}
    assert [pid for pid, _ in env.registry.providers(Capability.DISCOVERY)] == [gid]
    assert [pid for pid, _ in host.routers()] == [gid]
    with env.uow() as uow:
        state = uow.plugin_state.get(GOOD_GUID)
    assert state is not None
    assert state.installed_version == "1.0.0"


@pytest.mark.parametrize(
    ("plugin", "word"),
    [
        (BadSdkPlugin, "sdk"),
        (CrashSetupPlugin, "boom"),
        (UndeclaredPlugin, "undeclared"),
    ],
)
def test_invalid_plugins_marked_failed_with_reason(env: HostEnv, plugin: Any, word: str) -> None:
    host = env.host([plugin])
    host.load_all()

    info = host.get(env.id(plugin))
    assert info.state == "failed"
    assert info.error is not None
    assert word in info.error
    assert env.registry.providers(Capability.TRAFFIC) == []
    assert host.routers() == []


def _tables(path: Path) -> set[str]:
    engine = make_plugin_engine(path)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_plugin_tables_live_in_own_file(env: HostEnv) -> None:
    env.host([GoodPlugin]).load_all()

    own = plugin_data_file(env.data_dir, GOOD_GUID)
    assert {"items", "alembic_version"} <= _tables(own)
    assert "items" not in inspect(env.engine).get_table_names()


def test_no_storage_no_file(env: HostEnv) -> None:
    host = env.host([DeclaresPlugin])
    host.load_all()

    assert host.get(env.id(DeclaresPlugin)).state == "active"
    assert not (env.data_dir / "plugin-data").exists()


def test_disabled_plugin_makes_no_data_file(env: HostEnv) -> None:
    env.host([GoodPlugin], {GOOD_GUID: {"enabled": False}}).load_all()
    assert not plugin_data_file(env.data_dir, GOOD_GUID).exists()


def test_failed_plugin_does_not_stop_others(env: HostEnv) -> None:
    host = env.host([CrashSetupPlugin, GoodPlugin, UndeclaredPlugin])
    host.load_all()

    states = {i.id: i.state for i in host.list()}
    assert states == {
        env.id(CrashSetupPlugin): "failed",
        env.id(GoodPlugin): "active",
        env.id(UndeclaredPlugin): "failed",
    }
    assert env.registry.providers(Capability.DISCOVERY)


def test_undiscoverable_plugin_listed_as_failed(env: HostEnv) -> None:
    host = env.host([], extra=[DiscoveredPlugin("entry_point:broken", None, "ImportError: nope")])
    host.load_all()
    [info] = host.list()
    assert info.state == "failed"
    assert info.error is not None
    assert "nope" in info.error


def test_seed_used_only_on_first_run(env: HostEnv) -> None:
    seeds = {GOOD_GUID: {"level": 5}}
    first = env.host([GoodPlugin], seeds)
    first.load_all()
    gid = env.id(GoodPlugin)
    assert first.get(gid).settings == {"level": 5}
    first.update_settings(gid, {"level": 7})

    second = env.host([GoodPlugin], seeds)
    second.load_all()
    assert second.get(gid).settings == {"level": 7}


def test_seed_enabled_flag_disables_plugin(env: HostEnv) -> None:
    host = env.host([GoodPlugin], {GOOD_GUID: {"enabled": False}})
    host.load_all()
    assert host.get(env.id(GoodPlugin)).state == "disabled"
    assert env.registry.providers(Capability.DISCOVERY) == []
    assert "items" not in inspect(env.engine).get_table_names()


def test_invalid_stored_settings_fail_the_plugin(env: HostEnv) -> None:
    host = env.host([GoodPlugin], {GOOD_GUID: {"level": "x"}})
    host.load_all()
    info = host.get(env.id(GoodPlugin))
    assert info.state == "failed"
    assert info.error is not None
    assert "level" in info.error
    assert env.registry.providers(Capability.DISCOVERY) == []


def test_update_settings_invalid_raises(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    with pytest.raises(ValidationError) as excinfo:
        host.update_settings(env.id(GoodPlugin), {"level": "x"})
    assert "level" in str(excinfo.value)
    assert host.get(env.id(GoodPlugin)).settings == {"level": 1}


def test_update_settings_applies_and_restarts_jobs(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    env.scheduler.calls.clear()

    gid = env.id(GoodPlugin)
    info = host.update_settings(gid, {"level": 3})

    assert info.settings == {"level": 3}
    assert env.scheduler.calls == [("remove_owner", gid, ""), ("add", gid, "tick")]


def test_start_jobs_schedules_active_plugins_only(env: HostEnv) -> None:
    host = env.host([GoodPlugin, CrashSetupPlugin])
    host.load_all()
    host.start_jobs()
    assert env.scheduler.calls == [("add", env.id(GoodPlugin), "tick")]


def test_set_enabled_requires_restart(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()

    gid = env.id(GoodPlugin)
    off = host.set_enabled(gid, False)
    assert off.enabled is False
    assert off.restart_required is True
    assert off.state == "active"
    assert env.registry.providers(Capability.DISCOVERY)  # still loaded until restart

    back = host.set_enabled(gid, True)
    assert back.restart_required is False

    host.set_enabled(gid, False)
    restarted = env.host([GoodPlugin])
    restarted.load_all()
    assert restarted.get(gid).state == "disabled"
    assert restarted.get(gid).restart_required is False


def test_settings_schema_exposed(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    schema = host.get(env.id(GoodPlugin)).settings_schema
    assert schema is not None
    assert "level" in schema["properties"]


def test_shutdown_stops_jobs(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    env.scheduler.calls.clear()
    host.shutdown()
    assert env.scheduler.calls == [("remove_owner", env.id(GoodPlugin), "")]


def test_unknown_plugin_raises_not_found(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    with pytest.raises(NotFoundError):
        host.get("nope")


def test_check_plugin_contract_passes_for_good() -> None:
    check_plugin(GoodPlugin)


@pytest.mark.parametrize("plugin", [BadSdkPlugin, CrashSetupPlugin, UndeclaredPlugin])
def test_check_plugin_contract_rejects_bad_plugins(plugin: Any) -> None:
    with pytest.raises(AssertionError):
        check_plugin(plugin)


def test_get_plugin_masks_secret(env: HostEnv) -> None:
    host = env.host([SecretivePlugin])
    host.load_all()
    sid = env.id(SecretivePlugin)
    info = host.update_settings(sid, {"key": "s3cr3t"})
    assert host.get(sid).settings["key"] == "********"
    assert "s3cr3t" not in PluginOut.model_validate(info).model_dump_json()


def test_patch_mask_round_trip_keeps_secret(env: HostEnv) -> None:
    host = env.host([SecretivePlugin])
    host.load_all()
    sid = env.id(SecretivePlugin)
    host.update_settings(sid, {"key": "s3cr3t"})
    host.update_settings(sid, {"key": "********", "level": 4})

    plugin = host.plugin(sid)
    assert isinstance(plugin, SecretivePlugin)
    assert plugin.ctx is not None
    assert plugin.ctx.settings.key.get_secret_value() == "s3cr3t"
    assert plugin.ctx.settings.level == 4
    with env.uow() as uow:
        state = uow.plugin_state.get(SecretivePlugin.manifest.guid)
    assert state is not None
    assert state.settings["key"] == "s3cr3t"


def test_settings_schema_marks_password(env: HostEnv) -> None:
    host = env.host([SecretivePlugin])
    host.load_all()
    schema = host.get(env.id(SecretivePlugin)).settings_schema
    assert schema is not None
    prop = schema["properties"]["key"]
    candidates = [prop, *prop.get("anyOf", [])]
    assert any(c.get("writeOnly") is True for c in candidates)


def test_disabled_plugin_masks_secret(env: HostEnv) -> None:
    host = env.host([SecretivePlugin], {SecretivePlugin.manifest.guid: {"enabled": False, "key": "s3cr3t"}})
    host.load_all()
    info = host.get(env.id(SecretivePlugin))
    assert info.state == "disabled"
    assert info.settings["key"] == "********"


def test_invalid_stored_settings_error_has_no_secret(env: HostEnv, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    host = env.host([SecretivePlugin], {SecretivePlugin.manifest.guid: {"key": 12345, "level": "not-an-int"}})
    host.load_all()
    info = host.get(env.id(SecretivePlugin))
    assert info.state == "failed"
    assert info.error is not None
    assert "level" in info.error
    assert "12345" not in info.error
    assert "not-an-int" not in info.error
    assert "12345" not in caplog.text
    assert info.settings["key"] == "********"


def test_unmaskable_secret_fails_closed(env: HostEnv, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    host = env.host(
        [NestedSecretPlugin, SecretivePlugin],
        {NestedSecretPlugin.manifest.guid: {"login": {"password": "hunter22"}}},
    )
    host.load_all()
    info = host.get(env.id(NestedSecretPlugin))
    assert info.state == "failed"
    assert info.error is not None
    assert "cannot mask" in info.error
    assert "Credentials.properties.password" in info.error
    assert "hunter22" not in str(info.settings) + info.error + caplog.text
    assert host.get(env.id(SecretivePlugin)).state == "active"
