import pytest
from conftest import HostEnv
from sample_plugins.good import GoodPlugin
from sample_plugins.needy import NeedyPlugin

from netview.domain.errors import ValidationError
from netview.presentation.api.schemas import PluginOut


def test_a_plugin_without_requirements_is_configured(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    info = host.get(env.id(GoodPlugin))
    assert info.configured is True
    assert info.config_errors == {}


def test_defaults_that_miss_requirements_leave_it_active_but_unconfigured(env: HostEnv) -> None:
    host = env.host([NeedyPlugin])
    host.load_all()
    info = host.get(env.id(NeedyPlugin))
    assert info.state == "active"
    assert info.configured is False
    assert info.config_errors == {"host": "Required", "token": "Required"}
    out = PluginOut.model_validate(info).model_dump()
    assert out["configured"] is False
    assert out["config_errors"] == {"host": "Required", "token": "Required"}


def test_seeded_settings_that_meet_requirements_are_configured(env: HostEnv) -> None:
    host = env.host([NeedyPlugin], {NeedyPlugin.manifest.guid: {"host": "h", "auth": "none"}})
    host.load_all()
    assert host.get(env.id(NeedyPlugin)).configured is True


def test_a_disabled_plugin_still_reports_what_it_lacks(env: HostEnv) -> None:
    host = env.host([NeedyPlugin], {NeedyPlugin.manifest.guid: {"enabled": False, "host": "h"}})
    host.load_all()
    info = host.get(env.id(NeedyPlugin))
    assert info.state == "disabled"
    assert info.config_errors == {"token": "Required"}


def test_an_incomplete_save_is_rejected_field_by_field(env: HostEnv) -> None:
    host = env.host([NeedyPlugin])
    host.load_all()
    with pytest.raises(ValidationError) as excinfo:
        host.update_settings(env.id(NeedyPlugin), {"host": "h"})
    assert excinfo.value.fields == {"token": "Required"}
    assert "token" in str(excinfo.value)
    with env.uow() as uow:
        state = uow.plugin_state.get(NeedyPlugin.manifest.guid)
    assert state is not None
    assert state.settings == {}
    assert host.get(env.id(NeedyPlugin)).configured is False


def test_an_invalid_value_is_reported_on_its_field(env: HostEnv) -> None:
    host = env.host([NeedyPlugin])
    host.load_all()
    with pytest.raises(ValidationError) as excinfo:
        host.update_settings(env.id(NeedyPlugin), {"host": "h", "token": "t", "level": 99})
    assert set(excinfo.value.fields) == {"level"}
    assert "less than or equal to 9" in excinfo.value.fields["level"]


def test_a_complete_save_makes_it_configured(env: HostEnv) -> None:
    host = env.host([NeedyPlugin])
    host.load_all()
    info = host.update_settings(env.id(NeedyPlugin), {"host": "h", "token": "t"})
    assert info.configured is True
    assert info.config_errors == {}
    # a later save that leaves the stored secret in place still counts it
    assert host.update_settings(env.id(NeedyPlugin), {"token": "", "level": 2}).configured is True


def test_after_a_restart_a_complete_save_stays_configured(env: HostEnv) -> None:
    host = env.host([NeedyPlugin])
    host.load_all()
    host.update_settings(env.id(NeedyPlugin), {"host": "h", "token": "t"})
    restarted = env.host([NeedyPlugin])
    restarted.load_all()
    assert restarted.get(env.id(NeedyPlugin)).configured is True
