import logging
from typing import Any

import pytest
from conftest import HostEnv
from sample_plugins.bad_prefix import BadPrefixPlugin
from sample_plugins.bad_sdk import BadSdkPlugin
from sample_plugins.crash_setup import CrashSetupPlugin
from sample_plugins.good import GoodPlugin
from sample_plugins.secretive import SecretivePlugin
from sample_plugins.undeclared import UndeclaredPlugin
from sqlalchemy import inspect

from netview.application.capabilities import Capability
from netview.domain.errors import NotFoundError, ValidationError
from netview.infrastructure.plugins.discovery import DiscoveredPlugin
from netview.presentation.api.schemas import PluginOut
from netview.sdk.testing.contract import check_plugin


def test_good_plugin_active_and_registered(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()

    info = host.get("good")
    assert info.state == "active"
    assert info.error is None
    assert info.settings == {"level": 1}
    assert [pid for pid, _ in env.registry.providers(Capability.DISCOVERY)] == ["good"]
    tables = set(inspect(env.engine).get_table_names())
    assert {"good_items", "alembic_version_good"} <= tables
    assert [pid for pid, _ in host.routers()] == ["good"]
    with env.uow() as uow:
        state = uow.plugin_state.get("good")
    assert state is not None
    assert state.installed_version == "1.0.0"


@pytest.mark.parametrize(
    ("plugin", "plugin_id", "word"),
    [
        (BadPrefixPlugin, "bad_prefix", "prefix"),
        (BadSdkPlugin, "bad_sdk", "sdk"),
        (CrashSetupPlugin, "crash_setup", "boom"),
        (UndeclaredPlugin, "undeclared", "undeclared"),
    ],
)
def test_invalid_plugins_marked_failed_with_reason(
    env: HostEnv, plugin: Any, plugin_id: str, word: str
) -> None:
    host = env.host([plugin])
    host.load_all()

    info = host.get(plugin_id)
    assert info.state == "failed"
    assert info.error is not None
    assert word in info.error
    assert env.registry.providers(Capability.TRAFFIC) == []
    assert host.routers() == []


def test_bad_prefix_creates_no_tables(env: HostEnv) -> None:
    env.host([BadPrefixPlugin]).load_all()
    assert "items" not in inspect(env.engine).get_table_names()


def test_failed_plugin_does_not_stop_others(env: HostEnv) -> None:
    host = env.host([CrashSetupPlugin, GoodPlugin, UndeclaredPlugin])
    host.load_all()

    states = {i.id: i.state for i in host.list()}
    assert states == {"crash_setup": "failed", "good": "active", "undeclared": "failed"}
    assert env.registry.providers(Capability.DISCOVERY)


def test_undiscoverable_plugin_listed_as_failed(env: HostEnv) -> None:
    host = env.host([], extra=[DiscoveredPlugin("entry_point:broken", None, "ImportError: nope")])
    host.load_all()
    [info] = host.list()
    assert info.state == "failed"
    assert info.error is not None
    assert "nope" in info.error


def test_seed_used_only_on_first_run(env: HostEnv) -> None:
    seeds = {"good": {"level": 5}}
    first = env.host([GoodPlugin], seeds)
    first.load_all()
    assert first.get("good").settings == {"level": 5}
    first.update_settings("good", {"level": 7})

    second = env.host([GoodPlugin], seeds)
    second.load_all()
    assert second.get("good").settings == {"level": 7}


def test_seed_enabled_flag_disables_plugin(env: HostEnv) -> None:
    host = env.host([GoodPlugin], {"good": {"enabled": False}})
    host.load_all()
    assert host.get("good").state == "disabled"
    assert env.registry.providers(Capability.DISCOVERY) == []
    assert "good_items" not in inspect(env.engine).get_table_names()


def test_invalid_stored_settings_fail_the_plugin(env: HostEnv) -> None:
    host = env.host([GoodPlugin], {"good": {"level": "x"}})
    host.load_all()
    info = host.get("good")
    assert info.state == "failed"
    assert info.error is not None
    assert "level" in info.error
    assert env.registry.providers(Capability.DISCOVERY) == []


def test_update_settings_invalid_raises(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    with pytest.raises(ValidationError) as excinfo:
        host.update_settings("good", {"level": "x"})
    assert "level" in str(excinfo.value)
    assert host.get("good").settings == {"level": 1}


def test_update_settings_applies_and_restarts_jobs(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    env.scheduler.calls.clear()

    info = host.update_settings("good", {"level": 3})

    assert info.settings == {"level": 3}
    assert env.scheduler.calls == [("remove_owner", "good", ""), ("add", "good", "tick")]


def test_start_jobs_schedules_active_plugins_only(env: HostEnv) -> None:
    host = env.host([GoodPlugin, CrashSetupPlugin])
    host.load_all()
    host.start_jobs()
    assert env.scheduler.calls == [("add", "good", "tick")]


def test_set_enabled_requires_restart(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()

    off = host.set_enabled("good", False)
    assert off.enabled is False
    assert off.restart_required is True
    assert off.state == "active"
    assert env.registry.providers(Capability.DISCOVERY)  # still loaded until restart

    back = host.set_enabled("good", True)
    assert back.restart_required is False

    host.set_enabled("good", False)
    restarted = env.host([GoodPlugin])
    restarted.load_all()
    assert restarted.get("good").state == "disabled"
    assert restarted.get("good").restart_required is False


def test_settings_schema_exposed(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    schema = host.get("good").settings_schema
    assert schema is not None
    assert "level" in schema["properties"]


def test_shutdown_stops_jobs(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    env.scheduler.calls.clear()
    host.shutdown()
    assert env.scheduler.calls == [("remove_owner", "good", "")]


def test_unknown_plugin_raises_not_found(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    with pytest.raises(NotFoundError):
        host.get("nope")


def test_check_plugin_contract_passes_for_good() -> None:
    check_plugin(GoodPlugin)


@pytest.mark.parametrize("plugin", [BadPrefixPlugin, BadSdkPlugin, CrashSetupPlugin, UndeclaredPlugin])
def test_check_plugin_contract_rejects_bad_plugins(plugin: Any) -> None:
    with pytest.raises(AssertionError):
        check_plugin(plugin)


def test_get_plugin_masks_secret(env: HostEnv) -> None:
    host = env.host([SecretivePlugin])
    host.load_all()
    info = host.update_settings("secretive", {"key": "s3cr3t"})
    assert host.get("secretive").settings["key"] == "********"
    assert "s3cr3t" not in PluginOut.model_validate(info).model_dump_json()


def test_patch_mask_round_trip_keeps_secret(env: HostEnv) -> None:
    host = env.host([SecretivePlugin])
    host.load_all()
    host.update_settings("secretive", {"key": "s3cr3t"})
    host.update_settings("secretive", {"key": "********", "level": 4})

    plugin = host.plugin("secretive")
    assert isinstance(plugin, SecretivePlugin)
    assert plugin.ctx is not None
    assert plugin.ctx.settings.key.get_secret_value() == "s3cr3t"
    assert plugin.ctx.settings.level == 4
    with env.uow() as uow:
        state = uow.plugin_state.get("secretive")
    assert state is not None
    assert state.settings["key"] == "s3cr3t"


def test_settings_schema_marks_password(env: HostEnv) -> None:
    host = env.host([SecretivePlugin])
    host.load_all()
    schema = host.get("secretive").settings_schema
    assert schema is not None
    prop = schema["properties"]["key"]
    candidates = [prop, *prop.get("anyOf", [])]
    assert any(c.get("writeOnly") is True for c in candidates)


def test_disabled_plugin_masks_secret(env: HostEnv) -> None:
    host = env.host([SecretivePlugin], {"secretive": {"enabled": False, "key": "s3cr3t"}})
    host.load_all()
    info = host.get("secretive")
    assert info.state == "disabled"
    assert info.settings["key"] == "********"


def test_invalid_stored_settings_error_has_no_secret(env: HostEnv, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    host = env.host([SecretivePlugin], {"secretive": {"key": 12345, "level": "not-an-int"}})
    host.load_all()
    info = host.get("secretive")
    assert info.state == "failed"
    assert info.error is not None
    assert "level" in info.error
    assert "12345" not in info.error
    assert "not-an-int" not in info.error
    assert "12345" not in caplog.text
    assert info.settings["key"] == "********"
